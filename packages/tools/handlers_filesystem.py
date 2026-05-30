"""File-local built-in tool handlers."""

from __future__ import annotations

import difflib
import fnmatch
from collections.abc import Mapping
from contextlib import contextmanager, redirect_stdout
import io
import os
from pathlib import Path
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from typing import Any

from .handler_support import (
    coerce_bool,
    coerce_env,
    coerce_int,
    join_parts,
    optional_string,
    resolve_allowed_path,
    tool_summary,
)
from .rtk import append_rtk_failure_tail
from .runtime import ToolInvocation
from .surfaces import BuiltinToolDependencies

MAX_FILE_READ_LINES = 500
MAX_FILE_READ_LIMIT = 2_000
MAX_FILE_READ_CHARS = 100_000
MAX_FILE_LINE_CHARS = 2_000

_BLOCKED_DEVICE_PATHS = frozenset(
    {
        "/dev/zero",
        "/dev/random",
        "/dev/urandom",
        "/dev/full",
        "/dev/stdin",
        "/dev/stdout",
        "/dev/stderr",
        "/dev/tty",
        "/dev/console",
        "/dev/fd/0",
        "/dev/fd/1",
        "/dev/fd/2",
    }
)
_BINARY_EXTENSIONS = frozenset(
    {
        ".7z",
        ".avi",
        ".bin",
        ".bmp",
        ".class",
        ".dll",
        ".dmg",
        ".doc",
        ".docx",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".mov",
        ".mp3",
        ".mp4",
        ".o",
        ".pdf",
        ".png",
        ".pyc",
        ".so",
        ".tar",
        ".tgz",
        ".wasm",
        ".webp",
        ".xls",
        ".xlsx",
        ".zip",
    }
)
_SENSITIVE_SYSTEM_PREFIXES = (
    Path("/etc"),
    Path("/boot"),
    Path("/usr/lib/systemd"),
    Path("/private/etc"),
)
_SENSITIVE_EXACT_PATHS = (
    Path("/var/run/docker.sock"),
    Path("/run/docker.sock"),
)
_SENSITIVE_HOME_EXACT_NAMES = (
    ".bash_profile",
    ".bashrc",
    ".env",
    ".netrc",
    ".npmrc",
    ".pgpass",
    ".profile",
    ".pypirc",
    ".zprofile",
    ".zshrc",
)
_SENSITIVE_HOME_PREFIX_NAMES = (
    ".aws",
    ".azure",
    ".docker",
    ".git",
    ".gnupg",
    ".hg",
    ".kube",
    ".ssh",
)
_MODEL_SENSITIVE_DIR_NAMES = frozenset({".aws", ".ssh"})
_MODEL_SENSITIVE_SEARCH_GLOBS = (
    "!**/.env*",
    "!**/.ssh/**",
    "!**/.aws/**",
    "!**/.config/gh/**",
    "!**/.codex/auth.json",
    "!**/.qwen/oauth_creds.json",
    "!**/.elephant/**/provider-secrets.key",
    "!**/provider-secrets.key",
    "!**/gateway-local-secrets.json",
    "!**/*.auth-secrets.json",
    "!**/*.auth-profiles.json",
    "!**/*auth*.db",
    "!**/*auth*.sqlite",
    "!**/*auth*.sqlite3",
    "!**/*secret*.db",
    "!**/*secret*.sqlite",
    "!**/*secret*.sqlite3",
    "!**/*credential*.db",
    "!**/*credential*.sqlite",
    "!**/*credential*.sqlite3",
)
_MODEL_SENSITIVE_DB_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
_MODEL_SENSITIVE_DB_MARKERS = ("auth", "secret", "credential", "token")


def run_terminal_exec(
    invocation: ToolInvocation,
    *,
    dependencies: BuiltinToolDependencies,
) -> Mapping[str, Any]:
    command = str(invocation.arguments.get("command") or "").strip()
    if not command:
        raise ValueError("tool.terminal.exec requires a 'command' argument")
    allowed_roots = (*invocation.context.allowed_roots, *dependencies.additional_allowed_roots)
    local_root = dependencies.resolve_cwd(invocation.session_id)
    cwd = resolve_allowed_path(
        local_root,
        optional_string(invocation.arguments.get("cwd")),
        must_exist=True,
        allowed_roots=allowed_roots,
    )
    env = dict(invocation.context.env)
    env.update(coerce_env(invocation.arguments.get("env")))
    env = _terminal_execution_env(env)
    background = coerce_bool(invocation.arguments.get("background"), default=False)
    if background:
        managed = dependencies.process_manager.start(command=command, cwd=cwd, env=env)
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
        )
    timeout_seconds = max(1, min(coerce_int(invocation.arguments.get("timeout_seconds"), default=20), 120))
    rewrite_result = (
        dependencies.terminal_command_rewriter.rewrite(command, env=env)
        if dependencies.terminal_command_rewriter is not None else None
    )
    run_command = str(getattr(rewrite_result, "command", command) or command)
    trace_metadata = rewrite_result.trace_metadata() if rewrite_result is not None else {}
    returncode, stdout, stderr, timed_out, cancelled = _run_foreground_terminal_command(
        run_command,
        cwd=cwd,
        env=env,
        timeout_seconds=timeout_seconds,
        cancel_check=invocation.context.cancel_check,
    )
    body = join_parts(stdout, stderr)
    if cancelled:
        summary = join_parts(body, "command cancelled")
        return tool_summary(
            invocation,
            append_rtk_failure_tail(summary, rewrite_result),
            outcome="cancelled",
            side_effects=("terminal", "filesystem"),
            trace_metadata=trace_metadata,
        )
    if timed_out:
        summary = join_parts(body, f"command timed out after {timeout_seconds} seconds")
        return tool_summary(
            invocation,
            append_rtk_failure_tail(summary, rewrite_result),
            outcome="failed",
            side_effects=("terminal", "filesystem"),
            trace_metadata=trace_metadata,
        )
    summary = body or f"command exited with status {returncode}"
    if returncode != 0:
        summary = append_rtk_failure_tail(summary, rewrite_result)
        return tool_summary(
            invocation,
            summary,
            outcome="failed",
            side_effects=("terminal", "filesystem"),
            trace_metadata=trace_metadata,
        )
    return tool_summary(invocation, summary, side_effects=("terminal", "filesystem"), trace_metadata=trace_metadata)


def _run_foreground_terminal_command(
    command: str,
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
    cancel_check: Any = None,
) -> tuple[int, str, str, bool, bool]:
    session_kwargs: dict[str, Any] = {}
    if os.name == "posix":
        session_kwargs["start_new_session"] = True
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **session_kwargs,
    )
    deadline = time.monotonic() + max(1, timeout_seconds)
    while True:
        if callable(cancel_check):
            try:
                if cancel_check():
                    _terminate_terminal_process_group(process)
                    stdout, stderr = _communicate_after_terminal_stop(process)
                    return process.returncode, stdout, stderr, False, True
            except Exception:
                pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_terminal_process_group(process)
            stdout, stderr = _communicate_after_terminal_stop(process)
            return process.returncode, stdout, stderr, True, False
        try:
            stdout, stderr = process.communicate(timeout=min(0.2, remaining))
            return process.returncode, stdout, stderr, False, False
        except subprocess.TimeoutExpired:
            continue


def _communicate_after_terminal_stop(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        return process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        _kill_terminal_process_group(process)
        return process.communicate()


def _terminate_terminal_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=1)
            return
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            pass
    else:
        process.terminate()
        try:
            process.wait(timeout=1)
            return
        except subprocess.TimeoutExpired:
            pass
    _kill_terminal_process_group(process)


def _kill_terminal_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:
        process.kill()
    process.wait(timeout=1)


def run_file_read(
    invocation: ToolInvocation,
    *,
    cwd: Path,
    allowed_roots: tuple[Path, ...] = (),
    file_read_optimizer: Any | None = None,
) -> Mapping[str, Any]:
    raw_path = optional_string(invocation.arguments.get("path"))
    if raw_path is None:
        raise ValueError("tool.file.read requires a 'path' argument")
    path = resolve_allowed_path(cwd, raw_path, must_exist=True, allowed_roots=allowed_roots)
    if not path.is_file():
        raise ValueError(f"tool.file.read requires a file path: {raw_path}")
    if _is_model_request(invocation):
        _ensure_model_safe_read_path(path)
    _ensure_text_readable(path, raw_path=raw_path)
    content = path.read_text(encoding="utf-8", errors="replace")
    explicit_offset = "offset" in invocation.arguments and invocation.arguments.get("offset") is not None
    explicit_limit = "limit" in invocation.arguments and invocation.arguments.get("limit") is not None
    offset = max(1, coerce_int(invocation.arguments.get("offset"), default=1))
    limit = max(1, min(coerce_int(invocation.arguments.get("limit"), default=MAX_FILE_READ_LINES), MAX_FILE_READ_LIMIT))
    lines = content.splitlines()
    end_line = min(len(lines), offset + limit - 1)
    selected = lines[offset - 1 : end_line]
    selected_chars = sum(len(line) + 1 for line in selected)
    trace_metadata: Mapping[str, Any] = {}
    if file_read_optimizer is not None:
        optimization = file_read_optimizer.optimize_file_read(
            path=path,
            explicit_offset=explicit_offset,
            explicit_limit=explicit_limit,
            selected_chars=selected_chars,
            total_lines=len(lines),
            env=invocation.context.env,
        )
        trace_metadata = optimization.trace_metadata()
        if getattr(optimization, "optimized", False) and getattr(optimization, "summary", ""):
            return tool_summary(
                invocation,
                str(optimization.summary),
                side_effects=("file", "read"),
                trace_metadata=trace_metadata,
            )
    if selected_chars > MAX_FILE_READ_CHARS:
        raise ValueError(
            f"tool.file.read selected {selected_chars:,} characters, above the "
            f"{MAX_FILE_READ_CHARS:,} character limit; use a smaller offset/limit window"
        )
    numbered = "\n".join(
        f"{index}|{_truncate_line(line)}" for index, line in enumerate(selected, start=offset)
    )
    truncated = end_line < len(lines)
    header = [
        f"path: {path}",
        f"lines: {offset}-{end_line} of {len(lines)}",
        f"truncated: {str(truncated).lower()}",
    ]
    if truncated:
        header.append(f"hint: use offset={end_line + 1} limit={limit} to continue")
    if numbered:
        header.append(numbered)
    return tool_summary(
        invocation,
        "\n".join(header).strip(),
        side_effects=("file", "read"),
        trace_metadata=trace_metadata,
    )


def run_file_write(
    invocation: ToolInvocation,
    *,
    cwd: Path,
    allowed_roots: tuple[Path, ...] = (),
) -> Mapping[str, Any]:
    raw_path = optional_string(invocation.arguments.get("path"))
    content = invocation.arguments.get("content")
    if raw_path is None or content is None:
        raise ValueError("tool.file.write requires 'path' and 'content'")
    path = resolve_allowed_path(cwd, raw_path, must_exist=False, allowed_roots=allowed_roots)
    _ensure_safe_write_path(path)
    if path.exists() and path.is_dir():
        raise ValueError(f"tool.file.write requires a file path, got directory: {raw_path}")
    old_content = ""
    if path.exists():
        _ensure_text_readable(path, raw_path=raw_path)
        old_content = path.read_text(encoding="utf-8", errors="replace")
    new_content = str(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding="utf-8")
    diff = _unified_diff(old_content, new_content, path)
    lint = _lint_after_write(path)
    lines = [
        f"path: {path}",
        "mode: overwrite",
        f"bytes: {len(new_content.encode('utf-8'))}",
        "diff:",
        diff.rstrip() or "<empty>",
    ]
    if lint:
        lines.extend(("lint:", lint))
    return tool_summary(
        invocation,
        "\n".join(lines),
        side_effects=("file", "write"),
    )


def run_file_patch(
    invocation: ToolInvocation,
    *,
    cwd: Path,
    allowed_roots: tuple[Path, ...] = (),
) -> Mapping[str, Any]:
    mode_arg = invocation.arguments.get("mode")
    if mode_arg is None:
        raise ValueError("tool.file.patch requires a 'mode' argument")
    mode = str(mode_arg).strip().lower()
    from .handlers_filesystem_patch import _run_file_replace_patch, _run_v4a_patch

    if mode == "replace":
        return _run_file_replace_patch(invocation, cwd=cwd, allowed_roots=allowed_roots)
    if mode == "patch":
        patch_text = optional_string(invocation.arguments.get("patch"))
        if patch_text is None:
            raise ValueError("tool.file.patch mode=patch requires a 'patch' argument")
        return _run_v4a_patch(invocation, patch_text=patch_text, cwd=cwd, allowed_roots=allowed_roots)
    raise ValueError("tool.file.patch mode must be replace or patch")


def run_file_search(
    invocation: ToolInvocation,
    *,
    cwd: Path,
    allowed_roots: tuple[Path, ...] = (),
) -> Mapping[str, Any]:
    target = str(invocation.arguments.get("target") or "content").strip().lower()
    glob = optional_string(invocation.arguments.get("glob"))
    if glob is None:
        glob = optional_string(invocation.arguments.get("include"))
    query = str(invocation.arguments.get("query") or "").strip()
    if not query:
        query = str(invocation.arguments.get("pattern") or "").strip()
    if not query and target != "files":
        raise ValueError("tool.file.search requires a 'query' argument unless target=files")
    raw_path = optional_string(invocation.arguments.get("path"))
    search_root = (
        resolve_allowed_path(cwd, raw_path, must_exist=True, allowed_roots=allowed_roots)
        if raw_path is not None
        else cwd.resolve()
    )
    if _is_model_request(invocation):
        _ensure_model_safe_search_path(search_root)
    _ensure_safe_search_path(search_root)
    limit = max(1, min(coerce_int(invocation.arguments.get("limit"), default=20), 200))
    offset = max(0, coerce_int(invocation.arguments.get("offset"), default=0))
    context = max(0, min(coerce_int(invocation.arguments.get("context"), default=0), 5))
    rg_path = shutil.which("rg")
    if target not in {"files", "content"}:
        raise ValueError("tool.file.search target must be content or files")
    if rg_path is not None:
        if target == "files":
            command = [rg_path, "--files", str(search_root)]
            if _is_model_request(invocation):
                command[1:1] = _model_sensitive_search_args()
            if glob or query:
                command[1:1] = ["-g", glob or query]
        else:
            command = [rg_path, "-n", "--no-heading", "--with-filename", "--smart-case"]
            if glob is not None:
                command.extend(["-g", glob])
            if _is_model_request(invocation):
                command.extend(_model_sensitive_search_args())
            if context:
                command.extend(["-C", str(context)])
            command.extend(["--", query, str(search_root)])
        lines, returncode, stderr = _collect_command_lines(
            command,
            cwd=cwd,
            max_lines=offset + limit + 1,
            timeout_seconds=20,
        )
    else:
        lines, returncode, stderr = _collect_python_search_lines(
            target=target,
            query=query,
            glob=glob,
            search_root=search_root,
            model_request=_is_model_request(invocation),
            context=context,
            max_lines=offset + limit + 1,
        )
    if returncode not in {0, 1, -15}:
        raise RuntimeError(stderr or f"file search failed with status {returncode}")
    visible = lines[offset : offset + limit]
    truncated = len(lines) > offset + limit
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
        summary = f"no file matches for query: {query or glob or '*'}"
    return tool_summary(invocation, summary, side_effects=("file", "search"))


def _terminal_execution_env(extra_env: Mapping[str, str]) -> dict[str, str]:
    env = {**os.environ, **dict(extra_env)}
    shim_dir = _python_shim_dir()
    if shim_dir is None:
        return env
    path = env.get("PATH", "")
    needs_python = shutil.which("python", path=path) is None
    needs_python3 = shutil.which("python3", path=path) is None
    if needs_python or needs_python3:
        env["PATH"] = f"{path}{os.pathsep if path else ''}{shim_dir}"
    return env


def _python_shim_dir() -> str | None:
    python_path = Path(sys.executable).resolve()
    if not python_path.exists():
        return None
    base = Path(os.environ.get("TMPDIR") or "/tmp") / "elephant-agent-tool-shims"
    try:
        base.mkdir(parents=True, exist_ok=True)
        for name in ("python", "python3"):
            shim = base / name
            _ensure_python_shim(shim, python_path)
    except OSError:
        return None
    return str(base)


def _ensure_python_shim(shim: Path, python_path: Path) -> None:
    if shim.is_symlink():
        if shim.resolve(strict=False) == python_path:
            return
        shim.unlink(missing_ok=True)
    if shim.exists():
        return
    try:
        shim.symlink_to(python_path)
        return
    except OSError:
        shim.write_text(f"#!/bin/sh\nexec {str(python_path)!r} \"$@\"\n", encoding="utf-8")
        shim.chmod(0o755)


def _collect_python_search_lines(
    *,
    target: str,
    query: str,
    glob: str | None,
    search_root: Path,
    model_request: bool,
    context: int,
    max_lines: int,
) -> tuple[list[str], int, str]:
    try:
        if target == "files":
            pattern = glob or query
            lines = [
                str(path)
                for path in _iter_search_files(search_root, model_request=model_request)
                if not pattern or _matches_file_glob(path, search_root, pattern)
            ]
            return lines[:max_lines], 0 if lines else 1, ""
        regex = _compile_search_regex(query)
        lines: list[str] = []
        for path in _iter_search_files(search_root, model_request=model_request):
            if glob is not None and not _matches_file_glob(path, search_root, glob):
                continue
            for match_line in _matching_file_lines(path, regex, context=context):
                lines.append(match_line)
                if len(lines) >= max_lines:
                    return lines, -15, ""
        return lines, 0 if lines else 1, ""
    except OSError as error:
        return [], 2, str(error)


def _iter_search_files(search_root: Path, *, model_request: bool) -> list[Path]:
    root = search_root.resolve()
    if root.is_file():
        return [root] if _search_file_allowed(root, model_request=model_request) else []
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        dir_path = Path(directory)
        dirnames[:] = [
            name
            for name in sorted(dirnames)
            if name not in {".git", ".hg", "__pycache__"}
            and _search_file_allowed(dir_path / name, model_request=model_request)
        ]
        for filename in sorted(filenames):
            path = dir_path / filename
            if _search_file_allowed(path, model_request=model_request):
                files.append(path)
    return files


def _search_file_allowed(path: Path, *, model_request: bool) -> bool:
    if model_request and _model_sensitive_path_reason(path) is not None:
        return False
    return path.suffix.lower() not in _BINARY_EXTENSIONS


def _matches_file_glob(path: Path, root: Path, pattern: str) -> bool:
    normalized = pattern.strip()
    if not normalized:
        return True
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    return (
        fnmatch.fnmatch(relative, normalized)
        or fnmatch.fnmatch(path.name, normalized)
        or Path(relative).match(normalized)
    )


def _compile_search_regex(query: str) -> re.Pattern[str]:
    flags = 0 if any(character.isupper() for character in query) else re.IGNORECASE
    try:
        return re.compile(query, flags)
    except re.error:
        return re.compile(re.escape(query), flags)


def _matching_file_lines(path: Path, regex: re.Pattern[str], *, context: int) -> list[str]:
    try:
        with path.open("rb") as handle:
            sample = handle.read(2048)
        if _looks_binary(sample):
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    matched_indexes = {index for index, line in enumerate(lines) if regex.search(line)}
    if not matched_indexes:
        return []
    visible_indexes: set[int] = set()
    for index in matched_indexes:
        start = max(0, index - context)
        end = min(len(lines), index + context + 1)
        visible_indexes.update(range(start, end))
    return [f"{path}:{index + 1}:{_truncate_line(lines[index])}" for index in sorted(visible_indexes)]


def _is_model_request(invocation: ToolInvocation) -> bool:
    requester = invocation.requester or invocation.context.requester
    return str(requester or "").strip().lower() == "model"


def _model_sensitive_search_args() -> list[str]:
    args: list[str] = []
    for pattern in _MODEL_SENSITIVE_SEARCH_GLOBS:
        args.extend(["-g", pattern])
    return args


def _ensure_model_safe_read_path(path: Path) -> None:
    reason = _model_sensitive_path_reason(path)
    if reason is not None:
        raise ValueError(f"tool.file.read refuses sensitive credential path for model requester: {reason}")


def _ensure_model_safe_search_path(path: Path) -> None:
    reason = _model_sensitive_path_reason(path)
    if reason is not None:
        raise ValueError(f"tool.file.search refuses sensitive credential path for model requester: {reason}")


def _model_sensitive_path_reason(path: Path) -> str | None:
    resolved = path.expanduser().resolve(strict=False)
    parts = resolved.parts
    name = resolved.name
    lower_name = name.lower()
    lowered_parts = tuple(part.lower() for part in parts)

    if any(part == ".env" or part.startswith(".env.") for part in lowered_parts):
        return str(path)
    if any(part in _MODEL_SENSITIVE_DIR_NAMES for part in lowered_parts):
        return str(path)
    if _contains_part_sequence(lowered_parts, (".config", "gh")):
        return str(path)
    if _contains_part_sequence(lowered_parts, (".codex", "auth.json")):
        return str(path)
    if _contains_part_sequence(lowered_parts, (".qwen", "oauth_creds.json")):
        return str(path)
    if ".elephant" in lowered_parts and lower_name == "provider-secrets.key":
        return str(path)
    if lower_name in {"provider-secrets.key", "gateway-local-secrets.json"}:
        return str(path)
    if lower_name.endswith(".auth-secrets.json") or lower_name.endswith(".auth-profiles.json"):
        return str(path)
    if resolved.suffix.lower() in _MODEL_SENSITIVE_DB_SUFFIXES:
        stem = resolved.stem.lower()
        if any(marker in stem for marker in _MODEL_SENSITIVE_DB_MARKERS):
            return str(path)
    return None


def _contains_part_sequence(parts: tuple[str, ...], sequence: tuple[str, ...]) -> bool:
    if not sequence or len(parts) < len(sequence):
        return False
    end = len(parts) - len(sequence) + 1
    return any(parts[index : index + len(sequence)] == sequence for index in range(end))


def _ensure_text_readable(path: Path, *, raw_path: str) -> None:
    literal = str(Path(raw_path).expanduser())
    if literal in _BLOCKED_DEVICE_PATHS or (
        literal.startswith("/proc/") and literal.endswith(("/fd/0", "/fd/1", "/fd/2"))
    ):
        raise ValueError(f"tool.file.read refuses device path that can block indefinitely: {raw_path}")
    if path.suffix.lower() in _BINARY_EXTENSIONS:
        raise ValueError(f"tool.file.read refuses likely binary file: {raw_path}")
    with path.open("rb") as handle:
        sample = handle.read(2048)
    if _looks_binary(sample):
        raise ValueError(f"tool.file.read refuses binary content: {raw_path}")


def _looks_binary(sample: bytes) -> bool:
    if not sample:
        return False
    if b"\0" in sample:
        return True
    non_text = sum(byte < 32 and byte not in (9, 10, 13) for byte in sample)
    return non_text / len(sample) > 0.30


def _truncate_line(line: str) -> str:
    if len(line) <= MAX_FILE_LINE_CHARS:
        return line
    return line[:MAX_FILE_LINE_CHARS].rstrip() + " ... [line truncated]"


def _ensure_safe_write_path(path: Path) -> None:
    resolved = path.expanduser().resolve(strict=False)
    home = Path.home().resolve()
    if resolved.name == ".env" or resolved.name.startswith(".env."):
        raise ValueError(f"refusing to write sensitive environment file: {path}")
    for exact_name in _SENSITIVE_HOME_EXACT_NAMES:
        if resolved == home / exact_name:
            raise ValueError(f"refusing to write sensitive home file: {path}")
    for prefix_name in _SENSITIVE_HOME_PREFIX_NAMES:
        if _path_is_relative_to(resolved, home / prefix_name):
            raise ValueError(f"refusing to write sensitive credential directory: {path}")
    if any(part in {".git", ".hg"} for part in resolved.parts):
        raise ValueError(f"refusing to write VCS metadata path: {path}")
    for exact in _SENSITIVE_EXACT_PATHS:
        if resolved == exact:
            raise ValueError(f"refusing to write sensitive system path: {path}")
    for prefix in _SENSITIVE_SYSTEM_PREFIXES:
        if _path_is_relative_to(resolved, prefix):
            raise ValueError(f"refusing to write sensitive system path: {path}")


def _ensure_safe_search_path(path: Path) -> None:
    resolved = path.expanduser().resolve(strict=False)
    home = Path.home().resolve()
    for exact_name in _SENSITIVE_HOME_EXACT_NAMES:
        if resolved == home / exact_name:
            raise ValueError(f"refusing to search sensitive home file: {path}")
    for prefix_name in _SENSITIVE_HOME_PREFIX_NAMES:
        if resolved == home / prefix_name or _path_is_relative_to(resolved, home / prefix_name):
            raise ValueError(f"refusing to search sensitive credential directory: {path}")
    if any(part in {".git", ".hg"} for part in resolved.parts):
        raise ValueError(f"refusing to search VCS metadata path: {path}")
    for exact in _SENSITIVE_EXACT_PATHS:
        if resolved == exact:
            raise ValueError(f"refusing to search sensitive system path: {path}")
    for prefix in _SENSITIVE_SYSTEM_PREFIXES:
        if _path_is_relative_to(resolved, prefix):
            raise ValueError(f"refusing to search sensitive system path: {path}")


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False

def _unified_diff(old_content: str, new_content: str, path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _lint_after_write(path: Path) -> str:
    if path.suffix != ".py":
        return ""
    completed = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode == 0:
        return "python: ok"
    return "python: " + join_parts(completed.stdout, completed.stderr)


def _collect_command_lines(
    command: list[str],
    *,
    cwd: Path,
    max_lines: int,
    timeout_seconds: int,
) -> tuple[list[str], int, str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lines: list[str] = []
    deadline = time.monotonic() + timeout_seconds
    assert process.stdout is not None
    try:
        while len(lines) < max_lines:
            if time.monotonic() > deadline:
                process.kill()
                break
            ready, _, _ = select.select([process.stdout], [], [], 0.05)
            if ready:
                line = process.stdout.readline()
                if line:
                    lines.append(line.rstrip("\n"))
                    continue
            if process.poll() is not None:
                remaining = process.stdout.readlines()
                lines.extend(line.rstrip("\n") for line in remaining[: max(0, max_lines - len(lines))])
                break
        if len(lines) >= max_lines and process.poll() is None:
            process.terminate()
        returncode = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        returncode = process.wait()
    assert process.stderr is not None
    stderr = process.stderr.read().strip()
    process.stdout.close()
    process.stderr.close()
    return lines, returncode, stderr


__all__ = [
    "run_file_patch",
    "run_file_read",
    "run_file_search",
    "run_file_write",
    "run_terminal_exec",
]
