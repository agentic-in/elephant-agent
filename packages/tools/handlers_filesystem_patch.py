"""Patch-mode helpers for file tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

from .handler_support import coerce_bool, join_parts, optional_string, resolve_allowed_path, tool_summary
from .runtime import ToolInvocation


def _run_file_replace_patch(
    invocation: ToolInvocation,
    *,
    cwd: Path,
    allowed_roots: tuple[Path, ...],
) -> Mapping[str, Any]:
    from .handlers_filesystem import _ensure_safe_write_path, _ensure_text_readable, _lint_after_write, _unified_diff

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
    from .handlers_filesystem import _ensure_safe_write_path, _ensure_text_readable, _lint_after_write, _unified_diff

    operations = _parse_v4a_patch(patch_text)
    if not operations:
        unified_changes = _plan_unified_diff_patch(patch_text, cwd=cwd, allowed_roots=allowed_roots)
        if not unified_changes:
            raise ValueError(
                "tool.file.patch mode=patch did not contain any file operations; expected V4A "
                "'*** Begin Patch' operations or standard unified diff headers ('--- a/file', '+++ b/file', '@@ ... @@')"
            )
        return _apply_unified_diff_changes(invocation, unified_changes)
    from .handlers_filesystem import _lint_after_write, _unified_diff

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
    from .handlers_filesystem import _ensure_safe_write_path

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
