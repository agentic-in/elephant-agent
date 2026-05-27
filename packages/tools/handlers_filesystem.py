"""File-local built-in tool handlers."""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from contextlib import contextmanager, redirect_stdout
import io
import os
from pathlib import Path
import select
import shutil
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
    completed = subprocess.run(
        run_command,
        shell=True,
        cwd=cwd,
        env={**os.environ, **env} if env else None,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    body = join_parts(completed.stdout, completed.stderr)
    summary = body or f"command exited with status {completed.returncode}"
    if completed.returncode != 0:
        summary = append_rtk_failure_tail(summary, rewrite_result)
        return tool_summary(
            invocation,
            summary,
            outcome="failed",
            side_effects=("terminal", "filesystem"),
            trace_metadata=trace_metadata,
        )
    return tool_summary(invocation, summary, side_effects=("terminal", "filesystem"), trace_metadata=trace_metadata)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(content), encoding="utf-8")
    return tool_summary(
        invocation,
        f"path: {path}\nmode: overwrite\nbytes: {len(str(content).encode('utf-8'))}",
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
    rg_path = shutil.which("rg")
    if rg_path is None:
        raise RuntimeError("tool.file.search requires rg to be installed")
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
    if target == "files":
        command = [rg_path, "--files", str(search_root)]
        if _is_model_request(invocation):
            command[1:1] = _model_sensitive_search_args()
        if glob or query:
            command[1:1] = ["-g", glob or query]
    elif target == "content":
        command = [rg_path, "-n", "--no-heading", "--with-filename", "--smart-case"]
        if glob is not None:
            command.extend(["-g", glob])
        if _is_model_request(invocation):
            command.extend(_model_sensitive_search_args())
        context = max(0, min(coerce_int(invocation.arguments.get("context"), default=0), 5))
        if context:
            command.extend(["-C", str(context)])
        command.extend(["--", query, str(search_root)])
    else:
        raise ValueError("tool.file.search target must be content or files")
    lines, returncode, stderr = _collect_command_lines(
        command,
        cwd=cwd,
        max_lines=offset + limit + 1,
        timeout_seconds=20,
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


def _run_file_replace_patch(
    invocation: ToolInvocation,
    *,
    cwd: Path,
    allowed_roots: tuple[Path, ...],
) -> Mapping[str, Any]:
    raw_path = optional_string(invocation.arguments.get("path"))
    old_string = invocation.arguments.get("old_string")
    new_string = invocation.arguments.get("new_string")
    if raw_path is None or old_string is None or new_string is None:
        raise ValueError("tool.file.patch replace mode requires 'path', 'old_string', and 'new_string'")
    path = resolve_allowed_path(cwd, raw_path, must_exist=True, allowed_roots=allowed_roots)
    _ensure_safe_write_path(path)
    _ensure_text_readable(path, raw_path=raw_path)
    content = path.read_text(encoding="utf-8", errors="replace")
    search_text = str(old_string)
    replace_all = coerce_bool(invocation.arguments.get("replace_all"), default=False)
    count = content.count(search_text)
    if count == 0:
        raise ValueError(f"tool.file.patch could not find old_string in {path}; read or search the file first")
    if count > 1 and not replace_all:
        raise ValueError(
            f"tool.file.patch found {count} matches in {path}; provide more context or set replace_all=true"
        )
    updated = content.replace(search_text, str(new_string), -1 if replace_all else 1)
    path.write_text(updated, encoding="utf-8")
    diff = _unified_diff(content, updated, path)
    lint = _lint_after_write(path)
    replaced = count if replace_all else 1
    lines = [
        f"path: {path}",
        f"replacements: {replaced}",
        f"mode: {'all' if replace_all else 'unique'}",
        "diff:",
        diff.rstrip() or "<empty>",
    ]
    if lint:
        lines.extend(("lint:", lint))
    return tool_summary(invocation, "\n".join(lines), side_effects=("file", "patch"))


def _run_v4a_patch(
    invocation: ToolInvocation,
    *,
    patch_text: str,
    cwd: Path,
    allowed_roots: tuple[Path, ...],
) -> Mapping[str, Any]:
    operations = _parse_v4a_patch(patch_text)
    if not operations:
        unified_changes = _plan_unified_diff_patch(patch_text, cwd=cwd, allowed_roots=allowed_roots)
        if not unified_changes:
            raise ValueError(
                "tool.file.patch mode=patch did not contain any file operations; expected V4A "
                "'*** Begin Patch' operations or standard unified diff headers ('--- a/file', '+++ b/file', '@@ ... @@')"
            )
        return _apply_unified_diff_changes(invocation, unified_changes)
    modified: list[Path] = []
    created: list[Path] = []
    deleted: list[Path] = []
    diffs: list[str] = []
    for operation in operations:
        op = operation["op"]
        raw_path = operation["path"]
        path = resolve_allowed_path(cwd, raw_path, must_exist=op != "add", allowed_roots=allowed_roots)
        _ensure_safe_write_path(path)
        if op == "add":
            if path.exists():
                raise ValueError(f"tool.file.patch add target already exists: {raw_path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            new_content = "\n".join(operation["new_lines"])
            if new_content and not new_content.endswith("\n"):
                new_content += "\n"
            path.write_text(new_content, encoding="utf-8")
            created.append(path)
            diffs.append(_unified_diff("", new_content, path))
        elif op == "delete":
            _ensure_text_readable(path, raw_path=raw_path)
            old_content = path.read_text(encoding="utf-8", errors="replace")
            path.unlink()
            deleted.append(path)
            diffs.append(_unified_diff(old_content, "", path))
        elif op == "update":
            _ensure_text_readable(path, raw_path=raw_path)
            old_content = path.read_text(encoding="utf-8", errors="replace")
            old_block = "\n".join(operation["old_lines"])
            new_block = "\n".join(operation["new_lines"])
            if old_block and not old_block.endswith("\n"):
                old_block += "\n"
            if new_block and not new_block.endswith("\n"):
                new_block += "\n"
            match_count = old_content.count(old_block)
            if match_count != 1:
                raise ValueError(
                    f"tool.file.patch expected exactly one patch context match in {raw_path}, found {match_count}"
                )
            new_content = old_content.replace(old_block, new_block, 1)
            path.write_text(new_content, encoding="utf-8")
            modified.append(path)
            diffs.append(_unified_diff(old_content, new_content, path))
        else:
            raise ValueError(f"unsupported patch operation: {op}")
    lint_lines = tuple(filter(None, (_lint_after_write(path) for path in (*modified, *created) if path.exists())))
    lines = [
        "mode: patch",
        f"files_modified: {', '.join(str(path) for path in modified) or '<none>'}",
        f"files_created: {', '.join(str(path) for path in created) or '<none>'}",
        f"files_deleted: {', '.join(str(path) for path in deleted) or '<none>'}",
        "diff:",
        "\n".join(item.rstrip() for item in diffs if item.strip()) or "<empty>",
    ]
    if lint_lines:
        lines.extend(("lint:", "\n".join(lint_lines)))
    return tool_summary(invocation, "\n".join(lines), side_effects=("file", "patch"))


def _plan_unified_diff_patch(
    patch_text: str,
    *,
    cwd: Path,
    allowed_roots: tuple[Path, ...],
) -> list[dict[str, Any]]:
    file_patches = _parse_unified_diff(patch_text)
    changes: list[dict[str, Any]] = []
    for file_patch in file_patches:
        old_path = str(file_patch["old_path"])
        new_path = str(file_patch["new_path"])
        is_add = old_path == "/dev/null"
        is_delete = new_path == "/dev/null"
        raw_path = new_path if not is_delete else old_path
        path = resolve_allowed_path(cwd, _strip_diff_path(raw_path), must_exist=not is_add, allowed_roots=allowed_roots)
        _ensure_safe_write_path(path)
        if is_add:
            if path.exists():
                raise ValueError(f"tool.file.patch unified diff add target already exists: {raw_path}")
            old_content = ""
            old_lines: list[str] = []
        else:
            _ensure_text_readable(path, raw_path=raw_path)
            old_content = path.read_text(encoding="utf-8", errors="replace")
            old_lines = old_content.splitlines()
        new_lines = _apply_unified_hunks(old_lines, tuple(file_patch["hunks"]), raw_path=raw_path)
        new_content = "\n".join(new_lines)
        if new_content:
            new_content += "\n"
        op = "delete" if is_delete else "add" if is_add else "update"
        changes.append(
            {
                "op": op,
                "path": path,
                "old_content": old_content,
                "new_content": "" if is_delete else new_content,
            }
        )
    return changes


def _apply_unified_diff_changes(invocation: ToolInvocation, changes: list[dict[str, Any]]) -> Mapping[str, Any]:
    modified: list[Path] = []
    created: list[Path] = []
    deleted: list[Path] = []
    diffs: list[str] = []
    for change in changes:
        path = change["path"]
        old_content = str(change["old_content"])
        new_content = str(change["new_content"])
        op = change["op"]
        if op == "delete":
            path.unlink()
            deleted.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_content, encoding="utf-8")
            if op == "add":
                created.append(path)
            else:
                modified.append(path)
        diffs.append(_unified_diff(old_content, new_content, path))
    lint_lines = tuple(filter(None, (_lint_after_write(path) for path in (*modified, *created) if path.exists())))
    lines = [
        "mode: patch",
        "format: unified-diff",
        f"files_modified: {', '.join(str(path) for path in modified) or '<none>'}",
        f"files_created: {', '.join(str(path) for path in created) or '<none>'}",
        f"files_deleted: {', '.join(str(path) for path in deleted) or '<none>'}",
        "diff:",
        "\n".join(item.rstrip() for item in diffs if item.strip()) or "<empty>",
    ]
    if lint_lines:
        lines.extend(("lint:", "\n".join(lint_lines)))
    return tool_summary(invocation, "\n".join(lines), side_effects=("file", "patch"))


def _parse_unified_diff(patch_text: str) -> list[dict[str, Any]]:
    lines = patch_text.splitlines()
    patches: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("--- "):
            if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
                index += 1
                continue
            if current is not None:
                patches.append(current)
            current = {
                "old_path": _diff_header_path(line[4:]),
                "new_path": _diff_header_path(lines[index + 1][4:]),
                "hunks": [],
            }
            index += 2
            continue
        if current is not None and line.startswith("@@ "):
            old_start, old_count, new_start, new_count = _parse_hunk_header(line)
            hunk_lines: list[tuple[str, str]] = []
            index += 1
            while index < len(lines):
                hunk_line = lines[index]
                if hunk_line.startswith("--- ") or hunk_line.startswith("@@ "):
                    index -= 1
                    break
                if hunk_line.startswith("\\ No newline at end of file"):
                    index += 1
                    continue
                marker = hunk_line[:1]
                if marker not in {" ", "-", "+"}:
                    raise ValueError(f"tool.file.patch invalid unified diff hunk line: {hunk_line!r}")
                hunk_lines.append((marker, hunk_line[1:]))
                index += 1
            current["hunks"].append(
                {
                    "old_start": old_start,
                    "old_count": old_count,
                    "new_start": new_start,
                    "new_count": new_count,
                    "lines": tuple(hunk_lines),
                }
            )
        index += 1
    if current is not None:
        patches.append(current)
    return [patch for patch in patches if patch["hunks"]]


def _diff_header_path(value: str) -> str:
    path = value.strip().split("\t", 1)[0].split(" ", 1)[0]
    return path.strip()


def _strip_diff_path(value: str) -> str:
    path = _diff_header_path(value)
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _parse_hunk_header(line: str) -> tuple[int, int, int, int]:
    import re

    match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
    if match is None:
        raise ValueError(f"tool.file.patch invalid unified diff hunk header: {line!r}")
    old_start = int(match.group(1))
    old_count = int(match.group(2) or "1")
    new_start = int(match.group(3))
    new_count = int(match.group(4) or "1")
    return old_start, old_count, new_start, new_count


def _apply_unified_hunks(
    old_lines: list[str],
    hunks: tuple[Mapping[str, Any], ...],
    *,
    raw_path: str,
) -> list[str]:
    new_lines: list[str] = []
    old_index = 0
    for hunk in hunks:
        hunk_lines = tuple(hunk["lines"])
        derived_old_count = sum(1 for marker, _payload in hunk_lines if marker in {" ", "-"})
        # Empty old-side hunks use the header start as the insertion point.
        if derived_old_count == 0:
            old_start = max(0, min(int(hunk["old_start"]), len(old_lines)))
        else:
            old_start = max(0, int(hunk["old_start"]) - 1)
        if old_start < old_index:
            raise ValueError(f"tool.file.patch overlapping unified diff hunks for {raw_path}")
        new_lines.extend(old_lines[old_index:old_start])
        cursor = old_start
        removed = added = 0
        for marker, payload in hunk_lines:
            if marker == " ":
                if cursor >= len(old_lines) or old_lines[cursor] != payload:
                    raise ValueError(f"tool.file.patch unified diff context mismatch in {raw_path}: {payload!r}")
                new_lines.append(payload)
                cursor += 1
            elif marker == "-":
                if cursor >= len(old_lines) or old_lines[cursor] != payload:
                    raise ValueError(f"tool.file.patch unified diff removal mismatch in {raw_path}: {payload!r}")
                cursor += 1
                removed += 1
            elif marker == "+":
                new_lines.append(payload)
                added += 1
        old_index = cursor
    new_lines.extend(old_lines[old_index:])
    return new_lines


def _parse_v4a_patch(patch_text: str) -> list[dict[str, Any]]:
    lines = patch_text.splitlines()
    operations: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_patch = False
    for line in lines:
        if line == "*** Begin Patch":
            in_patch = True
            continue
        if line == "*** End Patch":
            if current is not None:
                operations.append(current)
            break
        if not in_patch:
            continue
        if line.startswith("*** Add File: "):
            if current is not None:
                operations.append(current)
            current = {"op": "add", "path": line.removeprefix("*** Add File: ").strip(), "new_lines": []}
            continue
        if line.startswith("*** Delete File: "):
            if current is not None:
                operations.append(current)
            operations.append({"op": "delete", "path": line.removeprefix("*** Delete File: ").strip()})
            current = None
            continue
        if line.startswith("*** Update File: "):
            if current is not None:
                operations.append(current)
            current = {
                "op": "update",
                "path": line.removeprefix("*** Update File: ").strip(),
                "old_lines": [],
                "new_lines": [],
            }
            continue
        if current is None or line.startswith("@@"):
            continue
        if current["op"] == "add":
            if not line.startswith("+"):
                raise ValueError("add-file patch lines must start with '+'")
            current["new_lines"].append(line[1:])
        elif current["op"] == "update":
            marker = line[:1]
            payload = line[1:] if marker in {" ", "-", "+"} else line
            if marker in {" ", "-"}:
                current["old_lines"].append(payload)
            if marker in {" ", "+"}:
                current["new_lines"].append(payload)
    return operations


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
