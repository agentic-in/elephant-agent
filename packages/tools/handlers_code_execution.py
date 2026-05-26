"""Restricted Python code execution tool handler."""

from __future__ import annotations

import ast
from collections.abc import Mapping
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any

from .handler_support import coerce_int, join_parts, tool_summary
from .runtime import ToolInvocation, ToolRuntime

MAX_CODE_TOOL_CALLS = 50
MAX_CODE_STDOUT_CHARS = 50_000
MAX_CODE_STDERR_CHARS = 10_000
CODE_RESULT_PREFIX = "__ELEPHANT_RESULT_JSON__="
CODE_EXECUTION_MODES = frozenset({"project", "strict"})
SAFE_CODE_IMPORTS = frozenset(
    {
        "base64",
        "calendar",
        "collections",
        "collections.abc",
        "copy",
        "csv",
        "datetime",
        "decimal",
        "fractions",
        "functools",
        "hashlib",
        "heapq",
        "html",
        "itertools",
        "json",
        "math",
        "operator",
        "re",
        "statistics",
        "string",
        "textwrap",
        "time",
        "types",
        "uuid",
    }
)
SAFE_CODE_DUNDER_ATTRIBUTES = frozenset({"__name__"})
_CODE_TERMINAL_BLOCKED_ARGUMENTS = frozenset({"background", "pty"})


def run_code_execute(
    invocation: ToolInvocation,
    *,
    runtime: ToolRuntime,
    allowlist: tuple[str, ...],
    cwd: Path,
    code_launcher: object | None = None,
) -> Mapping[str, Any]:
    code = str(invocation.arguments.get("code") or "")
    if not code.strip():
        raise ValueError("tool.code.execute requires a 'code' argument")
    _validate_python_snippet(code)
    timeout_seconds = max(1, min(coerce_int(invocation.arguments.get("timeout_seconds"), default=10), 30))
    mode = str(invocation.arguments.get("mode") or "project").strip().lower()
    if mode not in CODE_EXECUTION_MODES:
        raise ValueError("tool.code.execute mode must be project or strict")

    # Check if a sandbox code launcher was injected by SandboxToolExecutor
    effective_launcher = code_launcher
    if effective_launcher is None:
        injected = invocation.arguments.get("__sandbox_code_launcher__")
        if injected is not None:
            effective_launcher = injected

    summary, tool_call_count = _run_code_subprocess(
        code,
        invocation=invocation,
        runtime=runtime,
        allowlist=allowlist,
        timeout_seconds=timeout_seconds,
        cwd=cwd,
        mode=mode,
        code_launcher=effective_launcher,
    )
    return tool_summary(
        invocation,
        f"{summary}\ntool_calls_made: {tool_call_count}".strip(),
        side_effects=("code", "python", "sandbox"),
    )


def _validate_python_snippet(code: str) -> None:
    tree = ast.parse(code, mode="exec")
    blocked_names = {
        "__import__",
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "globals",
        "help",
        "input",
        "locals",
        "open",
        "vars",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_safe_code_import(alias.name):
                    raise ValueError(f"tool.code.execute does not allow importing {alias.name}")
        if isinstance(node, ast.ImportFrom):
            if node.level:
                raise ValueError("tool.code.execute does not allow relative imports")
            module = node.module or ""
            if any(alias.name == "*" for alias in node.names):
                raise ValueError("tool.code.execute does not allow wildcard imports")
            if not _is_safe_code_import(module):
                raise ValueError(f"tool.code.execute does not allow importing {module}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in blocked_names:
            raise ValueError(f"tool.code.execute does not allow {node.func.id}()")
        if (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("__")
            and node.attr not in SAFE_CODE_DUNDER_ATTRIBUTES
        ):
            raise ValueError("tool.code.execute does not allow dunder attribute access")


def _is_safe_code_import(module_name: str) -> bool:
    return module_name in SAFE_CODE_IMPORTS


def _run_code_subprocess(
    code: str,
    *,
    invocation: ToolInvocation,
    runtime: ToolRuntime,
    allowlist: tuple[str, ...],
    timeout_seconds: int,
    cwd: Path,
    mode: str,
    code_launcher: object | None = None,
) -> tuple[str, int]:
    with tempfile.TemporaryDirectory(prefix="elephant-code-") as tempdir:
        root = Path(tempdir)
        child_cwd = _code_child_cwd(mode=mode, project_cwd=cwd, staging_cwd=root)
        child_python = _code_child_python(mode=mode)
        code_path = root / "snippet.py"
        runner_path = root / "runner.py"
        request_dir = root / "requests"
        response_dir = root / "responses"
        stdout_path = root / "stdout.txt"
        stderr_path = root / "stderr.txt"
        request_dir.mkdir()
        response_dir.mkdir()
        code_path.write_text(code, encoding="utf-8")
        runner_path.write_text(_code_runner_source(), encoding="utf-8")
        env = _code_subprocess_env(
            code_path=code_path,
            request_dir=request_dir,
            response_dir=response_dir,
            timeout_seconds=timeout_seconds,
        )
        tool_call_count = 0

        # Determine launcher: use provided sandbox launcher or default local
        use_sandbox_launcher = code_launcher is not None
        if use_sandbox_launcher:
            launcher = code_launcher

        if use_sandbox_launcher:
            # Sandbox launcher manages its own file handles
            process = launcher.start(
                runner_path=runner_path,
                child_cwd=child_cwd,
                env=env,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        else:
            stdout_file = stdout_path.open("wb")
            stderr_file = stderr_path.open("wb")
            process = subprocess.Popen(
                [child_python, str(runner_path)],
                cwd=child_cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
            )

        try:
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                tool_call_count = _serve_code_tool_requests(
                    request_dir=request_dir,
                    response_dir=response_dir,
                    runtime=runtime,
                    invocation=invocation,
                    allowlist=allowlist,
                    tool_call_count=tool_call_count,
                )
                if time.monotonic() > deadline:
                    process.kill()
                    process.wait(timeout=1)
                    raise RuntimeError(f"tool.code.execute timed out after {timeout_seconds} seconds")
                time.sleep(0.02)
            for _ in range(10):
                previous = tool_call_count
                tool_call_count = _serve_code_tool_requests(
                    request_dir=request_dir,
                    response_dir=response_dir,
                    runtime=runtime,
                    invocation=invocation,
                    allowlist=allowlist,
                    tool_call_count=tool_call_count,
                )
                if tool_call_count == previous:
                    break
                time.sleep(0.02)
        finally:
            if not use_sandbox_launcher:
                stdout_file.close()
                stderr_file.close()

        stdout_text = _read_limited_text(stdout_path, limit=MAX_CODE_STDOUT_CHARS)
        stderr_text = _read_limited_text(stderr_path, limit=MAX_CODE_STDERR_CHARS)
        if process.returncode != 0:
            raise RuntimeError(join_parts(f"code exited with status {process.returncode}", stderr_text))
        output, result_line = _extract_code_result(stdout_text)
        if output and result_line is not None:
            summary = f"{output}\nresult={result_line}"
        elif result_line is not None:
            summary = f"result={result_line}"
        else:
            summary = output or "code executed successfully"
        return summary, tool_call_count


def _code_subprocess_env(
    *,
    code_path: Path,
    request_dir: Path,
    response_dir: Path,
    timeout_seconds: int,
) -> dict[str, str]:
    safe_prefixes = ("PATH", "HOME", "USER", "LANG", "LC_", "TERM", "TMP", "TEMP", "SHELL", "VIRTUAL_ENV", "CONDA")
    secret_fragments = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "PASSWD", "AUTH")
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if any(fragment in key.upper() for fragment in secret_fragments):
            continue
        if any(key.startswith(prefix) for prefix in safe_prefixes):
            env[key] = value
    env.update(
        {
            "ELEPHANT_CODE_FILE": str(code_path),
            "ELEPHANT_CODE_REQUEST_DIR": str(request_dir),
            "ELEPHANT_CODE_RESPONSE_DIR": str(response_dir),
            "ELEPHANT_CODE_TIMEOUT_SECONDS": str(timeout_seconds),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def _code_child_cwd(*, mode: str, project_cwd: Path, staging_cwd: Path) -> Path:
    if mode != "project":
        return staging_cwd
    if project_cwd.exists() and project_cwd.is_dir():
        return project_cwd.resolve()
    return staging_cwd


def _code_child_python(*, mode: str) -> str:
    if mode != "project":
        return sys.executable
    if sys.platform == "win32":
        subdirs = ("Scripts",)
        exe_names = ("python.exe", "python3.exe")
    else:
        subdirs = ("bin",)
        exe_names = ("python", "python3")
    for env_var in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        root = os.environ.get(env_var, "").strip()
        if not root:
            continue
        for subdir in subdirs:
            for exe_name in exe_names:
                candidate = Path(root) / subdir / exe_name
                if candidate.is_file() and os.access(candidate, os.X_OK) and _is_usable_code_python(candidate):
                    return str(candidate)
    return sys.executable


def _is_usable_code_python(candidate: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(candidate), "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)"],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _serve_code_tool_requests(
    *,
    request_dir: Path,
    response_dir: Path,
    runtime: ToolRuntime,
    invocation: ToolInvocation,
    allowlist: tuple[str, ...],
    tool_call_count: int,
) -> int:
    for request_path in sorted(request_dir.glob("*.json")):
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request_id = str(request.get("id") or request_path.stem)
            tool_id = str(request.get("tool_id") or "")
            arguments = request.get("arguments") if isinstance(request.get("arguments"), Mapping) else {}
            if tool_id not in allowlist:
                response: Mapping[str, Any] = {"ok": False, "error": f"tool RPC is not allowed for {tool_id}"}
            elif tool_call_count >= MAX_CODE_TOOL_CALLS:
                response = {"ok": False, "error": f"tool.code.execute exceeded {MAX_CODE_TOOL_CALLS} nested tool calls"}
            elif tool_id == "tool.terminal.exec" and _blocked_code_terminal_arguments(arguments):
                blocked = ", ".join(sorted(_blocked_code_terminal_arguments(arguments)))
                response = {"ok": False, "error": f"tool.code.execute does not allow tool.terminal.exec arguments: {blocked}"}
            else:
                tool_call_count += 1
                result = runtime.invoke(
                    tool_id,
                    dict(arguments),
                    session_id=invocation.session_id,
                    requester=invocation.requester,
                )
                response = {
                    "ok": True,
                    "result": {
                        "execution_id": result.execution_id,
                        "outcome": result.outcome,
                        "summary": result.summary,
                        "side_effects": result.side_effects,
                    },
                }
            _write_code_response(response_dir / f"{request_id}.json", response)
        except Exception as error:
            fallback_id = request_path.stem
            _write_code_response(response_dir / f"{fallback_id}.json", {"ok": False, "error": str(error)})
        finally:
            request_path.unlink(missing_ok=True)
    return tool_call_count


def _blocked_code_terminal_arguments(arguments: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(argument for argument in _CODE_TERMINAL_BLOCKED_ARGUMENTS if argument in arguments)


def _write_code_response(path: Path, payload: Mapping[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def _code_runner_source() -> str:
    return r'''
from __future__ import annotations

import importlib
import json
import os
import sys
import time
import uuid

_SAFE_IMPORTS = {
    "base64",
    "calendar",
    "collections",
    "collections.abc",
    "copy",
    "csv",
    "datetime",
    "decimal",
    "fractions",
    "functools",
    "hashlib",
    "heapq",
    "html",
    "itertools",
    "json",
    "math",
    "operator",
    "re",
    "statistics",
    "string",
    "textwrap",
    "time",
    "types",
    "uuid",
}


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    del globals, locals
    if level:
        raise ImportError("relative imports are not allowed")
    if name not in _SAFE_IMPORTS:
        raise ImportError(f"import is not allowed: {name}")
    module = importlib.import_module(name)
    if not fromlist and "." in name:
        return importlib.import_module(name.split(".", 1)[0])
    return module


def _safe_builtins():
    return {
        "__import__": _safe_import,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "Exception": Exception,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "print": print,
        "pow": pow,
        "range": range,
        "repr": repr,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "type": type,
        "tuple": tuple,
        "ValueError": ValueError,
        "zip": zip,
    }


def tool(tool_id, arguments=None, /, **kwargs):
    payload = dict(arguments or {})
    payload.update(kwargs)
    request_id = uuid.uuid4().hex
    request_dir = os.environ["ELEPHANT_CODE_REQUEST_DIR"]
    response_dir = os.environ["ELEPHANT_CODE_RESPONSE_DIR"]
    timeout = float(os.environ.get("ELEPHANT_CODE_TIMEOUT_SECONDS", "30"))
    request_path = os.path.join(request_dir, request_id + ".json")
    tmp_path = request_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump({"id": request_id, "tool_id": tool_id, "arguments": payload}, handle, ensure_ascii=False)
    os.replace(tmp_path, request_path)
    response_path = os.path.join(response_dir, request_id + ".json")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(response_path):
            with open(response_path, "r", encoding="utf-8") as handle:
                response = json.load(handle)
            try:
                os.unlink(response_path)
            except OSError:
                pass
            if not response.get("ok"):
                raise RuntimeError(str(response.get("error") or "tool call failed"))
            return response.get("result")
        time.sleep(0.02)
    raise TimeoutError(f"tool call timed out: {tool_id}")


with open(os.environ["ELEPHANT_CODE_FILE"], "r", encoding="utf-8") as handle:
    source = handle.read()

namespace = {"__builtins__": _safe_builtins(), "json": json, "tool": tool}
locals_dict = {}
exec(compile(source, "<elephant-tool-code>", "exec"), namespace, locals_dict)
if "result" in locals_dict:
    print("__ELEPHANT_RESULT_JSON__=" + json.dumps(locals_dict["result"], ensure_ascii=False, default=repr))
'''.lstrip()


def _read_limited_text(path: Path, *, limit: int) -> str:
    payload = path.read_bytes()
    if len(payload) <= limit:
        return payload.decode("utf-8", errors="replace").strip()
    head_size = max(0, limit // 2)
    tail_size = max(0, limit - head_size)
    head = payload[:head_size].decode("utf-8", errors="replace")
    tail = payload[-tail_size:].decode("utf-8", errors="replace")
    omitted = len(payload) - head_size - tail_size
    return f"{head.rstrip()}\n... [output truncated, {omitted:,} bytes omitted] ...\n{tail.lstrip()}".strip()


def _extract_code_result(stdout_text: str) -> tuple[str, str | None]:
    if not stdout_text:
        return "", None
    output_lines: list[str] = []
    result_line: str | None = None
    for line in stdout_text.splitlines():
        if line.startswith(CODE_RESULT_PREFIX):
            result_line = line.removeprefix(CODE_RESULT_PREFIX)
        else:
            output_lines.append(line)
    return "\n".join(output_lines).strip(), result_line


__all__ = ["run_code_execute"]
