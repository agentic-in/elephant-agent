from __future__ import annotations

from collections.abc import Mapping
from email.message import Message
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.tools import BuiltinToolDependencies, handlers_code_execution
from packages.tools.builtins import builtin_tool_definitions
from packages.tools.local_roots import default_local_allowed_roots
from packages.tools.rtk import RtkFileReadOptimizationResult, RtkRewriteResult
from tests.unit.builtin_tools_test_support import BuiltinToolsTestBase


class _FakeUrlopenResponse:
    def __init__(
        self,
        body: str,
        *,
        content_type: str = "text/html; charset=utf-8",
        url: str = "https://example.com",
    ) -> None:
        self._body = body.encode("utf-8")
        self._url = url
        self.headers = Message()
        self.headers.add_header("Content-Type", content_type)

    def __enter__(self) -> "_FakeUrlopenResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self._body
        return self._body[:size]

    def geturl(self) -> str:
        return self._url


class _FakeTerminalRewriter:
    def __init__(self, rewritten_command: str) -> None:
        self.rewritten_command = rewritten_command
        self.calls: list[str] = []

    def rewrite(self, command: str, *, env: Mapping[str, str] | None = None) -> RtkRewriteResult:
        self.calls.append(command)
        return RtkRewriteResult(
            original_command=command,
            command=self.rewritten_command,
            enabled=True,
            rewritten=True,
            binary="/tmp/rtk",
            exit_code=3,
        )


class _FakeFileReadOptimizer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

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
        self.calls.append(
            {
                "path": path,
                "explicit_offset": explicit_offset,
                "explicit_limit": explicit_limit,
                "selected_chars": selected_chars,
                "total_lines": total_lines,
            }
        )
        if explicit_offset or explicit_limit:
            return RtkFileReadOptimizationResult(
                enabled=True,
                optimized=False,
                skipped_reason="exact_read",
                total_lines=total_lines,
            )
        return RtkFileReadOptimizationResult(
            summary=f"path: {path}\noptimized_by: rtk read\ncompact view",
            enabled=True,
            optimized=True,
            binary="/tmp/rtk",
            exit_code=0,
            input_chars=selected_chars,
            output_chars=64,
            total_lines=total_lines,
        )


class BuiltinToolsFileCodeTest(BuiltinToolsTestBase):
    def test_file_tools_can_write_patch_read_and_search_root_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            runtime = self._make_builtin_runtime(cwd=cwd)

            written = runtime.invoke(
                "tool.file.write",
                {
                    "path": "notes/plan.txt",
                    "content": "alpha\nbeta\n",
                },
                session_id="session-file",
            )
            patched = runtime.invoke(
                "tool.file.patch",
                {
                    "mode": "replace",
                    "path": "notes/plan.txt",
                    "old_string": "beta",
                    "new_string": "gamma",
                },
                session_id="session-file",
            )
            read = runtime.invoke(
                "tool.file.read",
                {"path": "notes/plan.txt"},
                session_id="session-file",
            )
            searched = runtime.invoke(
                "tool.file.search",
                {"query": "gamma", "path": "notes"},
                session_id="session-file",
            )

            self.assertEqual(written.outcome, "success")
            self.assertIn("notes/plan.txt", written.summary)
            self.assertEqual(patched.outcome, "success")
            self.assertIn("replacements: 1", patched.summary)
            self.assertIn("1|alpha", read.summary)
            self.assertIn("2|gamma", read.summary)
            self.assertIn("plan.txt:2:gamma", searched.summary)

    def test_file_tools_can_write_to_posix_tmp_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            runtime = self._make_builtin_runtime(cwd=cwd)
            target = Path("/tmp") / f"elephant-tool-test-{os.getpid()}-{id(self)}.txt"
            target.unlink(missing_ok=True)
            self.addCleanup(target.unlink, missing_ok=True)

            written = runtime.invoke(
                "tool.file.write",
                {
                    "path": str(target),
                    "content": "tmp ok\n",
                },
                session_id="session-posix-tmp-file",
            )
            read = runtime.invoke(
                "tool.file.read",
                {"path": str(target)},
                session_id="session-posix-tmp-file",
            )

            self.assertEqual(written.outcome, "success")
            self.assertIn("1|tmp ok", read.summary)

    def test_default_local_allowed_roots_include_posix_tmp(self) -> None:
        with mock.patch("packages.tools.local_roots.tempfile.gettempdir", return_value="/var/folders/example/T"):
            roots = default_local_allowed_roots()

        self.assertIn(Path("/tmp").resolve(), roots)
        self.assertIn(Path("/var/folders/example/T").resolve(), roots)

    def test_file_tools_can_access_configured_roots_outside_primary_root(self) -> None:
        with tempfile.TemporaryDirectory() as local_tmpdir, tempfile.TemporaryDirectory() as external_tmpdir:
            local_root = Path(local_tmpdir)
            external = Path(external_tmpdir)
            shared = external / "shared.txt"
            shared.write_text("outside root\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(
                cwd=local_root,
                dependencies=BuiltinToolDependencies(
                    cwd=local_root,
                    additional_allowed_roots=(external,),
                ),
            )

            read = runtime.invoke(
                "tool.file.read",
                {"path": str(shared)},
                session_id="session-external-file",
            )
            searched = runtime.invoke(
                "tool.file.search",
                {"query": "outside", "path": str(external)},
                session_id="session-external-file",
            )
            written = runtime.invoke(
                "tool.file.write",
                {
                    "path": str(external / "notes.txt"),
                    "content": "draft\n",
                },
                session_id="session-external-file",
            )
            patched = runtime.invoke(
                "tool.file.patch",
                {
                    "mode": "replace",
                    "path": str(external / "notes.txt"),
                    "old_string": "draft",
                    "new_string": "final",
                },
                session_id="session-external-file",
            )
            terminal = runtime.invoke(
                "tool.terminal.exec",
                {
                    "command": "pwd",
                    "cwd": str(external),
                },
                session_id="session-external-file",
            )

            self.assertIn("1|outside root", read.summary)
            self.assertIn("shared.txt:1:outside root", searched.summary)
            self.assertEqual(written.outcome, "success")
            self.assertEqual(patched.outcome, "success")
            self.assertEqual((external / "notes.txt").read_text(encoding="utf-8"), "final\n")
            self.assertIn(str(external), terminal.summary)

    def test_file_and_terminal_tools_default_to_session_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as root_tmpdir, tempfile.TemporaryDirectory() as fallback_tmpdir:
            root = Path(root_tmpdir)
            fallback = Path(fallback_tmpdir)
            roots = {
                "session-alpha": root / "alpha",
                "session-beta": root / "beta",
            }
            for resolved_root in roots.values():
                resolved_root.mkdir()
            runtime = self._make_builtin_runtime(
                cwd=fallback,
                dependencies=BuiltinToolDependencies(
                    cwd=fallback,
                    cwd_resolver=lambda session_id: roots[str(session_id)],
                ),
            )

            written = runtime.invoke(
                "tool.file.write",
                {
                    "path": "notes.txt",
                    "content": "alpha root\n",
                },
                session_id="session-alpha",
            )
            terminal = runtime.invoke(
                "tool.terminal.exec",
                {"command": "pwd"},
                session_id="session-beta",
            )

            self.assertEqual(written.outcome, "success")
            self.assertTrue((roots["session-alpha"] / "notes.txt").exists())
            self.assertFalse((fallback / "notes.txt").exists())
            self.assertIn(str(roots["session-beta"]), terminal.summary)

    def test_terminal_exec_uses_configured_foreground_rewriter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            rewriter = _FakeTerminalRewriter("printf rewritten")
            runtime = self._make_builtin_runtime(
                cwd=cwd,
                dependencies=BuiltinToolDependencies(
                    cwd=cwd,
                    terminal_command_rewriter=rewriter,
                ),
            )

            result = runtime.invoke(
                "tool.terminal.exec",
                {"command": "printf original"},
                session_id="session-rtk-terminal",
            )

        self.assertEqual(rewriter.calls, ["printf original"])
        self.assertEqual(result.summary, "rewritten")
        self.assertEqual(result.trace_metadata.get("rtk_rewritten"), "true")
        self.assertEqual(result.trace_metadata.get("rtk_exit_code"), "3")

    def test_terminal_exec_background_does_not_use_rewriter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            rewriter = _FakeTerminalRewriter("printf rewritten")
            runtime = self._make_builtin_runtime(
                cwd=cwd,
                dependencies=BuiltinToolDependencies(
                    cwd=cwd,
                    terminal_command_rewriter=rewriter,
                ),
            )

            result = runtime.invoke(
                "tool.terminal.exec",
                {"command": "printf original", "background": True},
                session_id="session-rtk-background",
            )

        self.assertEqual(rewriter.calls, [])
        self.assertIn("command: printf original", result.summary)

    def test_terminal_exec_appends_rtk_full_output_tail_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            full_output = cwd / "pytest.log"
            full_output.write_text("ImportError: cannot import name UTC\n", encoding="utf-8")
            command = (
                "printf 'Pytest: No tests collected\\n[full output: "
                f"{full_output}"
                "]\\n' >&2; exit 2"
            )
            runtime = self._make_builtin_runtime(
                cwd=cwd,
                dependencies=BuiltinToolDependencies(
                    cwd=cwd,
                    terminal_command_rewriter=_FakeTerminalRewriter(command),
                ),
            )

            result = runtime.invoke(
                "tool.terminal.exec",
                {"command": "pytest tests/unit/test_example.py"},
                session_id="session-rtk-failure-tail",
            )

        self.assertEqual(result.outcome, "failed")
        self.assertIn("ImportError: cannot import name UTC", result.summary)
        self.assertEqual(result.trace_metadata.get("rtk_rewritten"), "true")
        self.assertEqual(result.trace_metadata.get("rtk_exit_code"), "3")

    def test_file_read_uses_configured_optimizer_for_non_exact_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            text_file = cwd / "large.txt"
            text_file.write_text("\n".join(f"line-{index}" for index in range(1, 20)), encoding="utf-8")
            optimizer = _FakeFileReadOptimizer()
            runtime = self._make_builtin_runtime(
                cwd=cwd,
                dependencies=BuiltinToolDependencies(cwd=cwd, file_read_optimizer=optimizer),
            )

            result = runtime.invoke(
                "tool.file.read",
                {"path": "large.txt"},
                session_id="session-file-read-rtk",
            )

        self.assertEqual(result.outcome, "success")
        self.assertIn("optimized_by: rtk read", result.summary)
        self.assertEqual(result.trace_metadata.get("rtk_file_read_optimized"), "true")
        self.assertEqual(len(optimizer.calls), 1)

    def test_file_read_keeps_explicit_line_windows_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            text_file = cwd / "large.txt"
            text_file.write_text("\n".join(f"line-{index}" for index in range(1, 20)), encoding="utf-8")
            optimizer = _FakeFileReadOptimizer()
            runtime = self._make_builtin_runtime(
                cwd=cwd,
                dependencies=BuiltinToolDependencies(cwd=cwd, file_read_optimizer=optimizer),
            )

            result = runtime.invoke(
                "tool.file.read",
                {"path": "large.txt", "offset": 2, "limit": 2},
                session_id="session-file-read-rtk-exact",
            )

        self.assertIn("2|line-2", result.summary)
        self.assertIn("3|line-3", result.summary)
        self.assertNotIn("optimized_by: rtk read", result.summary)
        self.assertEqual(result.trace_metadata.get("rtk_file_read_optimized"), "false")
        self.assertEqual(result.trace_metadata.get("rtk_skip_reason"), "exact_read")

    def test_file_read_is_paginated_and_rejects_binary_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            text_file = cwd / "large.txt"
            text_file.write_text("\n".join(f"line-{index}" for index in range(1, 602)), encoding="utf-8")
            binary_file = cwd / "image.png"
            binary_file.write_bytes(b"\x89PNG\r\n\x1a\n")
            runtime = self._make_builtin_runtime(cwd=cwd)

            read = runtime.invoke(
                "tool.file.read",
                {"path": "large.txt"},
                session_id="session-file-read-guard",
            )

            self.assertIn("lines: 1-500 of 601", read.summary)
            self.assertIn("truncated: true", read.summary)
            self.assertIn("hint: use offset=501", read.summary)
            with self.assertRaisesRegex(ValueError, "likely binary"):
                runtime.invoke(
                    "tool.file.read",
                    {"path": "image.png"},
                    session_id="session-file-read-binary",
                )

    def test_model_file_read_and_search_reject_sensitive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            sensitive_files = (
                cwd / ".env",
                cwd / ".env.local",
                cwd / ".ssh" / "config",
                cwd / ".aws" / "credentials",
                cwd / ".config" / "gh" / "hosts.yml",
                cwd / ".codex" / "auth.json",
                cwd / ".qwen" / "oauth_creds.json",
                cwd / ".elephant" / "herd" / "provider-secrets.key",
                cwd / "gateway-local-secrets.json",
                cwd / "elephant.auth-secrets.json",
                cwd / "auth.db",
                cwd / "secret.sqlite3",
            )
            for path in sensitive_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("needle-secret\n", encoding="utf-8")
            (cwd / "notes.txt").write_text("needle-public\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            for path in sensitive_files:
                with self.subTest(path=path):
                    with self.assertRaisesRegex(ValueError, "sensitive credential path"):
                        runtime.invoke(
                            "tool.file.read",
                            {"path": str(path)},
                            session_id="session-sensitive-model-read",
                            requester="model",
                        )
                    with self.assertRaisesRegex(ValueError, "sensitive credential path"):
                        runtime.invoke(
                            "tool.file.search",
                            {"query": "needle", "path": str(path)},
                            session_id="session-sensitive-model-search",
                            requester="model",
                        )

            searched = runtime.invoke(
                "tool.file.search",
                {"query": "needle", "path": str(cwd)},
                session_id="session-sensitive-model-search-root",
                requester="model",
            )

            self.assertIn("notes.txt:1:needle-public", searched.summary)
            self.assertNotIn("needle-secret", searched.summary)

    def test_file_write_blocks_sensitive_home_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            with self.assertRaisesRegex(ValueError, "sensitive credential directory"):
                runtime.invoke(
                    "tool.file.write",
                    {"path": str(Path.home() / ".ssh" / "config"), "content": "Host *\n"},
                    session_id="session-sensitive-write",
                )
            with self.assertRaisesRegex(ValueError, "VCS metadata"):
                runtime.invoke(
                    "tool.file.write",
                    {"path": ".git/config", "content": "[core]\n"},
                    session_id="session-vcs-write",
                )

    def test_file_patch_requires_unique_match_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "dupes.txt").write_text("same\nsame\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            with self.assertRaisesRegex(ValueError, "found 2 matches"):
                runtime.invoke(
                    "tool.file.patch",
                    {
                        "mode": "replace",
                        "path": "dupes.txt",
                        "old_string": "same",
                        "new_string": "changed",
                    },
                    session_id="session-patch-unique",
                )

    def test_file_patch_accepts_standard_unified_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "plan.txt").write_text("alpha\nbeta\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            result = runtime.invoke(
                "tool.file.patch",
                {
                    "mode": "patch",
                    "patch": "\n".join(
                        (
                            "--- a/plan.txt",
                            "+++ b/plan.txt",
                            "@@ -1,2 +1,2 @@",
                            " alpha",
                            "-beta",
                            "+gamma",
                            "--- /dev/null",
                            "+++ b/new.txt",
                            "@@ -0,0 +1,1 @@",
                            "+created",
                        )
                    ),
                },
                session_id="session-unified-patch",
            )

            self.assertIn("format: unified-diff", result.summary)
            self.assertEqual((cwd / "plan.txt").read_text(encoding="utf-8"), "alpha\ngamma\n")
            self.assertEqual((cwd / "new.txt").read_text(encoding="utf-8"), "created\n")

    def test_file_patch_accepts_unified_diff_with_miscounted_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "plan.txt").write_text("alpha\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            result = runtime.invoke(
                "tool.file.patch",
                {
                    "mode": "patch",
                    "patch": "\n".join(
                        (
                            "--- a/plan.txt",
                            "+++ b/plan.txt",
                            "@@ -1,1 +1,1 @@",
                            " alpha",
                            "+beta",
                        )
                    ),
                },
                session_id="session-unified-miscounted-patch",
            )

            self.assertIn("format: unified-diff", result.summary)
            self.assertEqual((cwd / "plan.txt").read_text(encoding="utf-8"), "alpha\nbeta\n")

    def test_file_patch_positions_empty_old_side_unified_hunks_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "plan.txt").write_text("alpha\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            result = runtime.invoke(
                "tool.file.patch",
                {
                    "mode": "patch",
                    "patch": "\n".join(
                        (
                            "--- a/plan.txt",
                            "+++ b/plan.txt",
                            "@@ -1,0 +2,1 @@",
                            "+beta",
                        )
                    ),
                },
                session_id="session-unified-empty-old-side-patch",
            )

            self.assertIn("format: unified-diff", result.summary)
            self.assertEqual((cwd / "plan.txt").read_text(encoding="utf-8"), "alpha\nbeta\n")

    def test_file_search_applies_global_limit_and_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            for index in range(4):
                (cwd / f"match-{index}.txt").write_text(f"needle {index}\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            first_page = runtime.invoke(
                "tool.file.search",
                {"query": "needle", "limit": 2},
                session_id="session-search-page",
            )
            second_page = runtime.invoke(
                "tool.file.search",
                {"query": "needle", "limit": 2, "offset": 2},
                session_id="session-search-page",
            )

            self.assertIn("shown: 2", first_page.summary)
            self.assertIn("truncated: true", first_page.summary)
            self.assertIn("offset: 2", second_page.summary)

    def test_file_search_accepts_pattern_alias_for_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "test_memory.py").write_text("class TestmemoryRecall:\n    pass\n", encoding="utf-8")
            (cwd / "notes.py").write_text("class TestmemoryRecallIgnored:\n    pass\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            result = runtime.invoke(
                "tool.file.search",
                {
                    "include": "**/test_*.py",
                    "pattern": "class.*Test.*memory|class.*Test.*search|class.*Test.*recall",
                    "path": str(cwd),
                },
                session_id="session-search-pattern-alias",
            )

            self.assertIn("TestmemoryRecall", result.summary)
            self.assertNotIn("TestmemoryRecallIgnored", result.summary)

    def test_file_search_allows_glob_only_file_listing_and_blocks_vcs_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "notes.md").write_text("hello\n", encoding="utf-8")
            (cwd / "notes.txt").write_text("hello\n", encoding="utf-8")
            (cwd / ".git").mkdir()
            runtime = self._make_builtin_runtime(cwd=cwd)

            listed = runtime.invoke(
                "tool.file.search",
                {"target": "files", "glob": "*.md"},
                session_id="session-search-files",
            )

            self.assertIn("notes.md", listed.summary)
            self.assertNotIn("notes.txt", listed.summary)
            all_files = runtime.invoke(
                "tool.file.search",
                {"target": "files"},
                session_id="session-search-all-files",
            )
            self.assertIn("notes.md", all_files.summary)
            self.assertIn("notes.txt", all_files.summary)
            with self.assertRaisesRegex(ValueError, "VCS metadata"):
                runtime.invoke(
                    "tool.file.search",
                    {"query": "anything", "path": ".git"},
                    session_id="session-search-vcs",
                )

    def test_terminal_exec_background_processes_can_be_waited_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            started = runtime.invoke(
                "tool.terminal.exec",
                {
                    "command": 'python3 -c "import time; print(\'bg-finished\'); time.sleep(0.1)"',
                    "background": True,
                },
                session_id="session-process",
            )
            process_id = started.summary.splitlines()[0].split(": ", 1)[1]

            listed = runtime.invoke(
                "tool.process.manage",
                {"action": "list"},
                session_id="session-process",
            )
            waited = runtime.invoke(
                "tool.process.manage",
                {
                    "action": "wait",
                    "process_id": process_id,
                    "timeout_seconds": 2,
                },
                session_id="session-process",
            )

            self.assertIn(process_id, listed.summary)
            self.assertIn("status: exited(0)", waited.summary)
            self.assertIn("bg-finished", waited.summary)

    def test_process_manage_poll_drains_running_process_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            started = runtime.invoke(
                "tool.terminal.exec",
                {
                    "command": f"{sys.executable} -u -c \"import time; print('ready', flush=True); time.sleep(2)\"",
                    "background": True,
                },
                session_id="session-process-poll",
            )
            process_id = started.summary.splitlines()[0].split(": ", 1)[1]
            self.addCleanup(
                lambda: runtime.invoke(
                    "tool.process.manage",
                    {"action": "kill", "process_id": process_id},
                    session_id="session-process-poll",
                )
            )

            polled = runtime.invoke(
                "tool.process.manage",
                {"action": "poll", "process_id": process_id},
                session_id="session-process-poll",
            )

            self.assertIn("status: running", polled.summary)
            self.assertIn("ready", polled.summary)

    def test_terminal_exec_merges_env_overrides_with_parent_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            result = runtime.invoke(
                "tool.terminal.exec",
                {
                    "command": (
                        "python3 -c \"import os; "
                        "print(os.environ.get('ELEPHANT_TEST_ENV')); "
                        "print(bool(os.environ.get('PATH')))\""
                    ),
                    "env": {"ELEPHANT_TEST_ENV": "present"},
                },
                session_id="session-terminal-env",
            )

            self.assertIn("present", result.summary)
            self.assertIn("True", result.summary)

    def test_code_execute_can_call_allowlisted_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "context.txt").write_text("hello from elephant\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            result = runtime.invoke(
                "tool.code.execute",
                {
                    "code": "\n".join(
                        (
                            "result = tool('tool.file.read', {'path': 'context.txt'})",
                            "print('read-via-rpc')",
                        )
                    )
                },
                session_id="session-code",
            )

            self.assertEqual(result.outcome, "success")
            self.assertIn("read-via-rpc", result.summary)
            self.assertIn("1|hello from elephant", result.summary)
            self.assertIn("tool_calls_made: 1", result.summary)

    def test_model_code_execute_preserves_requester_for_nested_file_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / ".env").write_text("needle-secret\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            with self.assertRaisesRegex(RuntimeError, "sensitive credential path"):
                runtime.invoke(
                    "tool.code.execute",
                    {
                        "code": "result = tool('tool.file.read', {'path': '.env'})",
                    },
                    session_id="session-code-model-sensitive-read",
                    requester="model",
                )

    def test_code_execute_allows_safe_stdlib_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            result = runtime.invoke(
                "tool.code.execute",
                {
                    "code": "\n".join(
                        (
                            "import json",
                            "import re",
                            "from collections import Counter",
                            "counts = Counter(re.findall('a', 'banana'))",
                            "print(json.dumps({'a': counts['a']}, sort_keys=True))",
                        )
                    )
                },
                session_id="session-code-import-safe",
            )

            self.assertEqual(result.outcome, "success")
            self.assertIn('"a": 3', result.summary)

    def test_code_execute_documents_and_allows_copy_pow_and_safe_dunder_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            result = runtime.invoke(
                "tool.code.execute",
                {
                    "code": "\n".join(
                        (
                            "import copy",
                            "value = copy.copy({'n': pow(2, 5)})",
                            "try:",
                            "    raise ValueError('x')",
                            "except ValueError as error:",
                            "    print(type(error).__name__, value['n'])",
                        )
                    )
                },
                session_id="session-code-safe-more",
            )

            self.assertIn("ValueError 32", result.summary)

    def test_code_execute_schema_safe_imports_match_enforced_allowlist(self) -> None:
        definitions = {
            definition.tool_id: definition
            for definition in builtin_tool_definitions({}, dependencies=BuiltinToolDependencies(cwd=Path("/tmp")))
        }
        description = definitions["tool.code.execute"].schema["properties"]["code"]["description"]

        for module in handlers_code_execution.SAFE_CODE_IMPORTS:
            self.assertIn(module, description)
        for blocked in ("os", "sys", "random", "subprocess", "open()"):
            self.assertIn(blocked, description)
        self.assertIn("blocked", description)

    def test_code_execute_runs_with_project_cwd_and_venv_python_by_default(self) -> None:
        from packages.tools import handlers_code_execution

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            staging = root / "staging"
            project = root / "project"
            venv = root / "venv"
            staging.mkdir()
            project.mkdir()
            python_dir = venv / ("Scripts" if sys.platform == "win32" else "bin")
            python_dir.mkdir(parents=True)
            python_path = python_dir / ("python.exe" if sys.platform == "win32" else "python")
            if sys.platform == "win32":
                python_path.write_text("", encoding="utf-8")
            else:
                python_path.symlink_to(sys.executable)

            self.assertEqual(
                handlers_code_execution._code_child_cwd(mode="project", project_cwd=project, staging_cwd=staging),
                project.resolve(),
            )
            self.assertEqual(
                handlers_code_execution._code_child_cwd(mode="strict", project_cwd=project, staging_cwd=staging),
                staging,
            )
            with mock.patch.dict(os.environ, {"VIRTUAL_ENV": str(venv), "CONDA_PREFIX": ""}, clear=False):
                if sys.platform == "win32":
                    self.assertIn(
                        handlers_code_execution._code_child_python(mode="project"),
                        {str(python_path), sys.executable},
                    )
                else:
                    self.assertEqual(handlers_code_execution._code_child_python(mode="project"), str(python_path))
            self.assertEqual(handlers_code_execution._code_child_python(mode="strict"), sys.executable)

    def test_code_execute_can_call_terminal_but_rejects_background_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            result = runtime.invoke(
                "tool.code.execute",
                {
                    "code": "result = tool('tool.terminal.exec', {'command': 'printf terminal-ok'})",
                },
                session_id="session-code-terminal",
            )

            self.assertEqual(result.outcome, "success")
            self.assertIn("terminal-ok", result.summary)
            self.assertIn("tool_calls_made: 1", result.summary)

            with self.assertRaisesRegex(RuntimeError, "does not allow tool.terminal.exec arguments: background"):
                runtime.invoke(
                    "tool.code.execute",
                    {
                        "code": (
                            "result = tool('tool.terminal.exec', "
                            "{'command': 'printf blocked', 'background': True})"
                        ),
                    },
                    session_id="session-code-terminal-blocked",
                )

    def test_code_execute_caps_nested_tool_rpc_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "context.txt").write_text("hello from elephant\n", encoding="utf-8")
            runtime = self._make_builtin_runtime(cwd=cwd)

            with self.assertRaisesRegex(RuntimeError, "exceeded 50 nested tool calls"):
                runtime.invoke(
                    "tool.code.execute",
                    {
                        "code": "\n".join(
                            (
                                "for _ in range(51):",
                                "    tool('tool.file.read', {'path': 'context.txt'})",
                            )
                        )
                    },
                    session_id="session-code-cap",
                )

    def test_code_execute_can_write_files_and_extract_web_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            runtime = self._make_builtin_runtime(cwd=cwd)

            with mock.patch(
                "packages.tools.handlers_network.urlopen",
                return_value=_FakeUrlopenResponse(
                    "<html><head><title>Alpha Doc</title></head><body><p>First source excerpt.</p></body></html>",
                    url="https://example.com/alpha",
                ),
            ):
                result = runtime.invoke(
                    "tool.code.execute",
                    {
                        "code": "\n".join(
                            (
                                "tool('tool.file.write', {'path': 'notes/out.txt', 'content': 'saved by code\\n', 'create_parents': True})",
                                "tool('tool.file.patch', {'mode': 'replace', 'path': 'notes/out.txt', 'old_string': 'saved', 'new_string': 'patched'})",
                                "result = tool('tool.web.extract', {'urls': ['https://example.com/alpha']})",
                            )
                        )
                    },
                    session_id="session-code-write",
                )

            self.assertEqual(result.outcome, "success")
            self.assertEqual((cwd / 'notes' / 'out.txt').read_text(encoding='utf-8'), "patched by code\n")
            self.assertIn("Alpha Doc", result.summary)

    def test_code_execute_rejects_unsafe_imports_and_non_allowlisted_tool_rpc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            with self.assertRaisesRegex(ValueError, "does not allow importing os"):
                runtime.invoke(
                    "tool.code.execute",
                    {"code": "import os\nresult = 1"},
                    session_id="session-code-import",
                )
            with self.assertRaisesRegex(RuntimeError, "tool RPC is not allowed"):
                runtime.invoke(
                    "tool.code.execute",
                    {"code": "result = tool('tool.personal_model.search', {})"},
                    session_id="session-code-rpc-deny",
                )

    def test_code_execute_enforces_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._make_builtin_runtime(cwd=Path(tmpdir))

            with self.assertRaisesRegex(RuntimeError, "timed out after 1 seconds"):
                runtime.invoke(
                    "tool.code.execute",
                    {
                        "code": "while True:\n    pass",
                        "timeout_seconds": 1,
                    },
                    session_id="session-code-timeout",
                )



if __name__ == "__main__":
    unittest.main()
