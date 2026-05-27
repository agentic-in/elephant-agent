from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from packages.runtime_config import global_config_path_for_state_dir, save_rtk_to_config
from packages.tools import BuiltinToolDependencies, CallableApprovalGateway, build_tool_runtime
from packages.tools.rtk import RtkCommandRewriter, append_rtk_full_output_tail


def _fake_rtk(path: Path) -> Path:
    script = path / "fake-rtk"
    script.write_text(
        """#!/usr/bin/env python3
import os
import sys

mode = os.environ.get("FAKE_RTK_MODE", "allow")
if len(sys.argv) > 1 and sys.argv[1] == "--version":
    print("rtk 0.40.0")
    raise SystemExit(0)
if len(sys.argv) > 2 and sys.argv[1] == "rewrite":
    output = os.environ.get("FAKE_RTK_OUTPUT")
    if mode == "allow":
        print(output or ("rtk " + sys.argv[2]))
        raise SystemExit(0)
    if mode == "ask":
        print(output or ("rtk " + sys.argv[2]))
        raise SystemExit(3)
    if mode == "none":
        raise SystemExit(1)
    if mode == "deny":
        raise SystemExit(2)
    if mode == "error":
        print("boom", file=sys.stderr)
        raise SystemExit(9)
raise SystemExit(64)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


class RtkCommandRewriterTest(unittest.TestCase):
    def test_exit_zero_rewrites_command(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            binary = _fake_rtk(Path(tempdir))
            result = RtkCommandRewriter(enabled=True, binary=str(binary)).rewrite("git status")

        self.assertTrue(result.rewritten)
        self.assertEqual(result.command, "rtk git status")
        self.assertEqual(result.exit_code, 0)

    def test_exit_three_rewrites_command_without_auto_allowing(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            binary = _fake_rtk(Path(tempdir))
            result = RtkCommandRewriter(enabled=True, binary=str(binary)).rewrite(
                "git status",
                env={"FAKE_RTK_MODE": "ask"},
            )

        self.assertTrue(result.rewritten)
        self.assertEqual(result.command, "rtk git status")
        self.assertEqual(result.exit_code, 3)

    def test_no_rewrite_and_deny_fail_open_to_original_command(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            binary = _fake_rtk(Path(tempdir))
            no_match = RtkCommandRewriter(enabled=True, binary=str(binary)).rewrite(
                "sed -n 1,2p file.py",
                env={"FAKE_RTK_MODE": "none"},
            )
            denied = RtkCommandRewriter(enabled=True, binary=str(binary)).rewrite(
                "rm -rf tmp",
                env={"FAKE_RTK_MODE": "deny"},
            )

        self.assertFalse(no_match.rewritten)
        self.assertEqual(no_match.command, "sed -n 1,2p file.py")
        self.assertEqual(no_match.skipped_reason, "no_rewrite")
        self.assertFalse(denied.rewritten)
        self.assertEqual(denied.command, "rm -rf tmp")
        self.assertEqual(denied.skipped_reason, "denied")

    def test_missing_disabled_and_prefixed_commands_skip_rewrite(self) -> None:
        missing = RtkCommandRewriter(enabled=True, binary="/missing/rtk").rewrite("git status")
        disabled = RtkCommandRewriter(enabled=True, binary="rtk").rewrite(
            "git status",
            env={"RTK_DISABLED": "1"},
        )
        already = RtkCommandRewriter(enabled=True, binary="rtk").rewrite("rtk git status")

        self.assertEqual(missing.skipped_reason, "missing_binary")
        self.assertEqual(disabled.skipped_reason, "rtk_disabled")
        self.assertEqual(already.skipped_reason, "already_rtk")

    def test_full_output_tail_is_appended_for_rtk_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            log = Path(tempdir) / "pytest.log"
            log.write_text("line-1\nImportError: cannot import name UTC\n", encoding="utf-8")
            summary = append_rtk_full_output_tail(f"Pytest: No tests collected\n[full output: {log}]")

        self.assertIn("RTK full output tail", summary)
        self.assertIn("ImportError: cannot import name UTC", summary)

    def test_factory_loads_enabled_rtk_config_for_terminal_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state_dir = root / "state"
            binary = _fake_rtk(root)
            save_rtk_to_config(
                global_config_path_for_state_dir(state_dir),
                state_dir=state_dir,
                rtk_payload={"enabled": True, "binary": str(binary)},
            )
            runtime = build_tool_runtime(
                enabled_overrides={},
                dependencies=BuiltinToolDependencies(cwd=root),
                approval_gateway=CallableApprovalGateway(lambda *_: True),
                state_dir=state_dir,
            )

            result = runtime.invoke(
                "tool.terminal.exec",
                {
                    "command": "printf original",
                    "env": {"FAKE_RTK_OUTPUT": "printf rewritten"},
                },
                session_id="session-rtk-factory",
            )

        self.assertEqual(result.summary, "rewritten")
        self.assertEqual(result.trace_metadata.get("rtk_rewritten"), "true")


if __name__ == "__main__":
    unittest.main()
