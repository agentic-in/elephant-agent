# ruff: noqa: E402

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.cli.shell_progress import (
    _tool_trace_label,
    _tool_trace_preview,
    build_stream_response_window,
    build_turn_progress_window,
    kernel_event_tracker,
    live_tool_feed_lines,
    recall_progress_line,
    render_queued_followup_fragments,
    render_stream_response_fragments,
    render_tool_trace_fragments,
    tool_event_tracker,
    tool_event_progress_line,
    tool_event_progress_lines,
    tool_trace_line,
    loop_context_progress_line,
    turn_state_focus_progress_line,
    turn_phase,
    turn_usage_progress_line,
    visible_kernel_stage_events,
    visible_tool_events,
)
from apps.cli.shell_support_runtime import PendingShellCommand
from apps.cli.shell_methods_ui import _status_bar_elapsed_fragments
from packages.tools.runtime import ToolLifecycleEvent, ToolInvocation


class ShellProgressTest(unittest.TestCase):
    def _evidence_event(
        self,
        *,
        tool_id: str,
        action: str | None = None,
        evidence_id: str = "evidence-release",
    ) -> ToolLifecycleEvent:
        invocation = ToolInvocation(
            invocation_id="invoke-evidence",
            tool_id=tool_id,
            session_id="session-test",
            arguments=(
                {"evidence_id": evidence_id} if action is None else {"action": action, "evidence_id": evidence_id}
            ),
            requested_at=datetime.now(timezone.utc),
            requester="test",
        )
        return ToolLifecycleEvent(
            event_id="event-evidence",
            invocation=invocation,
            phase="requested",
            detail="requested",
        )

    def _tool_event(
        self,
        *,
        tool_id: str,
        arguments: dict[str, str],
        phase: str,
        detail: str = "",
    ) -> ToolLifecycleEvent:
        invocation = ToolInvocation(
            invocation_id=f"invoke-{tool_id}",
            tool_id=tool_id,
            session_id="session-test",
            arguments=arguments,
            requested_at=datetime.now(timezone.utc),
            requester="test",
        )
        return ToolLifecycleEvent(
            event_id=f"event-{tool_id}-{phase}",
            invocation=invocation,
            phase=phase,
            detail=detail,
            occurred_at=datetime.now(timezone.utc),
        )

    def test_personal_model_search_trace_uses_current_label_and_preview(self) -> None:
        event = self._tool_event(
            tool_id="tool.personal_model.search",
            arguments={"query": "release notes"},
            phase="requested",
        )

        self.assertEqual(_tool_trace_label(event), "model")
        self.assertEqual(
            _tool_trace_preview(event.invocation.arguments, tool_id="tool.personal_model.search"),
            "release notes",
        )

    def test_personal_model_update_requested_trace_uses_current_prepare_label(
        self,
    ) -> None:
        event = self._tool_event(
            tool_id="tool.personal_model.update",
            arguments={
                "action": "remember",
                "lens": "rapport",
                "topic": "assistant.review.style",
            },
            phase="requested",
        )

        self.assertEqual(
            tool_trace_line(None, event),
            "┊ 🌱 Calling learn · remember assistant.review.style…",
        )

    def test_personal_model_search_requested_trace_uses_current_label(self) -> None:
        event = self._tool_event(
            tool_id="tool.personal_model.search",
            arguments={"query": "notes"},
            phase="requested",
        )

        self.assertEqual(_tool_trace_label(event), "model")
        self.assertEqual(tool_trace_line(None, event), "┊ 🐘 Calling model · notes…")
        self.assertEqual(
            tool_event_progress_line(
                None,
                self._tool_event(
                    tool_id="tool.personal_model.search",
                    arguments={"query": "notes"},
                    phase="execution.started",
                ),
            ),
            "┊ 🐘 model        notes",
        )

    def test_conversation_search_trace_uses_current_label(self) -> None:
        search = self._tool_event(
            tool_id="tool.conversation.search",
            arguments={"query": "family", "expr": "last_night"},
            phase="requested",
        )
        discover = self._tool_event(
            tool_id="tool.conversation.search",
            arguments={"mode": "discover", "time_range": {"expr": "last:3d"}},
            phase="requested",
        )

        self.assertEqual(_tool_trace_label(search), "trail")
        self.assertEqual(tool_trace_line(None, search), "┊ 🐾 Calling trail · family…")
        self.assertEqual(_tool_trace_label(discover), "trail")
        self.assertEqual(tool_trace_line(None, discover), "┊ 🐾 Calling trail · last:3d…")

    def test_custom_mcp_requested_trace_uses_extension_emoji(self) -> None:
        event = self._tool_event(
            tool_id="mcp.km.hot-articles",
            arguments={"period": "2"},
            phase="requested",
        )

        self.assertEqual(tool_trace_line(None, event), "┊ 🧩 Calling mcp.km.hot-articles…")

    def test_custom_mcp_started_trace_uses_extension_emoji(self) -> None:
        event = self._tool_event(
            tool_id="mcp.km.hot-articles",
            arguments={"title": "Top KM"},
            phase="execution.started",
        )

        self.assertEqual(tool_event_progress_line(None, event), "┊ 🧩 mcp.km.hot-articles Top KM")

    def test_tool_event_tracker_keeps_short_lived_feed_for_fast_personal_model_events(
        self,
    ) -> None:
        holder, lock, observer = tool_event_tracker()
        requested = self._tool_event(
            tool_id="tool.personal_model.search",
            arguments={"query": "evidence-release"},
            phase="requested",
        )
        completed = ToolLifecycleEvent(
            event_id="event-evidence-complete",
            invocation=requested.invocation,
            phase="execution.completed",
            detail="done",
            occurred_at=datetime.now(timezone.utc),
        )

        observer(requested)
        observer(completed)
        feed = visible_tool_events(holder, lock)

        self.assertEqual([event.event.phase for event in feed], ["requested", "execution.completed"])

    def test_kernel_event_tracker_forwards_skill_disclosures_without_adding_fake_stage(
        self,
    ) -> None:
        captured: list[dict[str, object]] = []
        holder, lock, observer = kernel_event_tracker(captured.append)

        observer(
            {
                "event_type": "skill.disclosed",
                "payload": {
                    "skill_id": "skill.research.web",
                    "display_name": "Web research skill",
                },
            }
        )

        self.assertEqual(visible_kernel_stage_events(holder, lock), ())
        self.assertEqual(
            captured,
            [
                {
                    "event_type": "skill.disclosed",
                    "payload": {
                        "skill_id": "skill.research.web",
                        "display_name": "Web research skill",
                    },
                }
            ],
        )

    def test_kernel_event_tracker_keeps_context_compaction_visible_after_usage_events(
        self,
    ) -> None:
        holder, lock, observer = kernel_event_tracker()
        observer(
            {
                "event_type": "kernel.stage",
                "payload": {
                    "stage": "context-compact",
                    "detail": "reason=usage tokens=1800->620 messages=80->12",
                },
            }
        )
        for index in range(16):
            observer(
                {
                    "event_type": "kernel.stage",
                    "payload": {
                        "stage": "context-usage",
                        "detail": f"prompt_tokens={index + 1}",
                    },
                }
            )

        stages = visible_kernel_stage_events(holder, lock)

        self.assertTrue(any(stage["payload"]["stage"] == "context-compact" for stage in stages))
        self.assertTrue(any(stage["payload"]["stage"] == "context-usage" for stage in stages))

    def test_kernel_event_tracker_keeps_state_focus_visible_after_compaction_and_usage_events(
        self,
    ) -> None:
        holder, lock, observer = kernel_event_tracker()
        observer(
            {
                "event_type": "kernel.stage",
                "payload": {
                    "stage": "relationship",
                    "detail": "relationship=session continuity_notes=1",
                    "recorded_at": "2026-04-17T08:00:00+00:00",
                },
            }
        )
        observer(
            {
                "event_type": "kernel.stage",
                "payload": {
                    "stage": "state_focus",
                    "detail": (
                        "state_focus=resume confidence=0.94 focus=<none> scope=lineage "
                        "degradation=none weak_assist=false weak_outcome=not-requested fallback=none candidates=3"
                    ),
                    "recorded_at": "2026-04-17T08:00:00.149000+00:00",
                },
            }
        )
        observer(
            {
                "event_type": "kernel.stage",
                "payload": {
                    "stage": "context-compact",
                    "detail": "reason=usage tokens=57470->7500 messages=43->3",
                    "recorded_at": "2026-04-17T08:00:01+00:00",
                },
            }
        )
        for index in range(16):
            observer(
                {
                    "event_type": "kernel.stage",
                    "payload": {
                        "stage": "context-usage",
                        "detail": f"total_tokens={index + 1}",
                    },
                }
            )

        stages = visible_kernel_stage_events(holder, lock)
        line = turn_state_focus_progress_line(kernel_stage_events=stages)

        self.assertIn("resume · 149ms · lineage · conf 0.94", line)

    def test_recall_progress_line_shows_hit_count(self) -> None:
        line = recall_progress_line(
            kernel_stage_events=(
                {
                    "event_type": "kernel.stage",
                    "payload": {
                        "stage": "recall",
                        "detail": "status=hit count=2 bytes=128",
                    },
                },
            )
        )

        self.assertEqual(line, "┊ 🗺️ recall       linked 2 signals")

    def test_recall_progress_line_shows_no_match(self) -> None:
        line = recall_progress_line(
            kernel_stage_events=(
                {
                    "event_type": "kernel.stage",
                    "payload": {
                        "stage": "recall",
                        "detail": "status=miss count=0 bytes=0",
                    },
                },
            )
        )

        self.assertEqual(line, "┊ 🗺️ recall       no signal")

    def test_usage_progress_line_shows_projection_while_provider_usage_is_pending(
        self,
    ) -> None:
        line = turn_usage_progress_line(
            kernel_stage_events=(
                {
                    "event_type": "kernel.stage",
                    "payload": {
                        "stage": "context-projection",
                        "detail": "prompt_tokens=16000 token_budget=128000 source=generation",
                    },
                },
            )
        )

        self.assertEqual(
            line,
            "┊ 📈 request      provider running · sent est 16000/128000 · 12% · usage pending",
        )

    def test_terminal_progress_line_shows_shell_command(self) -> None:
        event = self._tool_event(
            tool_id="tool.terminal.exec",
            arguments={"command": "memo notes --help"},
            phase="execution.started",
        )

        self.assertEqual(_tool_trace_label(event), "computer")
        self.assertEqual(tool_event_progress_line(None, event), "┊ 💻 computer     memo notes --help")

    def test_file_read_progress_line_shows_file_path_detail(self) -> None:
        event = self._tool_event(
            tool_id="tool.file.read",
            arguments={"file_path": "/tmp/alpha.txt"},
            phase="execution.started",
        )

        self.assertEqual(_tool_trace_label(event), "read")
        self.assertEqual(tool_event_progress_line(None, event), "┊ 📖 read         /tmp/alpha.txt")

        local_event = self._tool_event(
            tool_id="tool.file.read",
            arguments={"file_path": str(Path.cwd() / "personal-model-test-report.md")},
            phase="execution.started",
        )
        local_line = tool_event_progress_line(None, local_event) or ""
        self.assertIn("personal-model-test-report.md", local_line)
        self.assertNotIn("\x1b]8;;", local_line)

    def test_sub_agents_progress_line_shows_name_and_prompt(self) -> None:
        event = self._tool_event(
            tool_id="tool.sub_agents",
            arguments={"name": "reviewer", "task": "inspect the cron scheduler"},
            phase="execution.started",
        )

        self.assertEqual(
            tool_event_progress_line(None, event),
            "┊ 🐘 herd         run · reviewer: inspect the cron scheduler",
        )

    def test_sub_agents_progress_line_shows_start_action(self) -> None:
        event = self._tool_event(
            tool_id="tool.sub_agents",
            arguments={
                "action": "start",
                "name": "reviewer",
                "task": "inspect the cron scheduler",
            },
            phase="execution.started",
        )

        self.assertEqual(
            tool_event_progress_line(None, event),
            "┊ 🐘 herd         start · reviewer: inspect the cron scheduler",
        )

    def test_sub_agents_progress_line_shows_status_action_and_run_id(self) -> None:
        event = self._tool_event(
            tool_id="tool.sub_agents",
            arguments={"action": "status", "run_id": "subrun-abc123"},
            phase="execution.started",
        )

        self.assertEqual(
            tool_event_progress_line(None, event),
            "┊ 🐘 herd         status · subrun-abc123",
        )

    def test_sub_agents_progress_lines_expand_batch_tasks(self) -> None:
        event = self._tool_event(
            tool_id="tool.sub_agents",
            arguments={
                "tasks": [
                    {"name": "core", "task": "read core architecture"},
                    {"name": "tools", "prompt": "inspect tool system"},
                ]
            },
            phase="execution.started",
        )

        self.assertEqual(
            tool_event_progress_lines(None, tool_event=event),
            (
                "┊ 🐘 herd         run · 2 agents",
                "┊   1. core: read core architecture",
                "┊   2. tools: inspect tool system",
            ),
        )

    def test_sub_agents_progress_lines_expand_batch_start_action(self) -> None:
        event = self._tool_event(
            tool_id="tool.sub_agents",
            arguments={
                "action": "start",
                "tasks": [
                    {"name": "core", "task": "read core architecture"},
                    {"name": "tools", "prompt": "inspect tool system"},
                ],
            },
            phase="execution.started",
        )

        self.assertEqual(
            tool_event_progress_lines(None, tool_event=event),
            (
                "┊ 🐘 herd         start · 2 agents",
                "┊   1. core: read core architecture",
                "┊   2. tools: inspect tool system",
            ),
        )

    def test_context_progress_line_surfaces_projection_compaction(self) -> None:
        line = loop_context_progress_line(
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "context-compact",
                        "detail": (
                            "reason=preflight tokens=1800->620 messages=80->12 "
                            "compacted_messages=68 tail=10 semantic_cached=2 semantic_pending=5 semantic_missed=1"
                        ),
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    }
                },
            )
        )

        self.assertIn("context", line)
        self.assertIn("🧩 context", line)
        self.assertIn("projection compact", line)
        self.assertIn("est 1800->620 tokens", line)
        self.assertIn("80->12 messages", line)
        self.assertIn("scanner: 2 cached / 5 pending / 1 missed", line)

    def test_context_progress_line_marks_projection_rewrite_when_tokens_do_not_shrink(
        self,
    ) -> None:
        line = loop_context_progress_line(
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "context-compact",
                        "detail": "reason=usage tokens=5489->5500 messages=10->7 compacted_messages=3 tail=7",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    }
                },
            )
        )

        self.assertIn("🧩 context", line)
        self.assertIn("projection rewrite", line)
        self.assertIn("est 5489->5500 tokens", line)
        self.assertIn("10->7 messages", line)
        self.assertIn("usage", line)

    def test_context_progress_line_keeps_fast_compaction_visible(self) -> None:
        line = loop_context_progress_line(
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "context-compact",
                        "detail": "reason=preflight tokens=1800->620 messages=80->12 compacted_messages=68 tail=10",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    }
                },
                {
                    "payload": {
                        "stage": "context",
                        "detail": "bundle=bundle:session budget=4096 recovery_scope_reason=test",
                        "recorded_at": "2026-04-17T08:00:00.250000+00:00",
                    }
                },
            ),
            now=datetime(2026, 4, 17, 8, 0, 1, tzinfo=timezone.utc),
        )

        self.assertIn("projection compact", line)
        self.assertIn("est 1800->620 tokens", line)

    def test_context_progress_line_returns_ready_after_compaction_hold(self) -> None:
        line = loop_context_progress_line(
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "context-compact",
                        "detail": "reason=preflight tokens=1800->620 messages=80->12 compacted_messages=68 tail=10",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    }
                },
                {
                    "payload": {
                        "stage": "context",
                        "detail": "bundle=bundle:session budget=4096 recovery_scope_reason=test",
                        "recorded_at": "2026-04-17T08:00:00.250000+00:00",
                    }
                },
            ),
            now=datetime(2026, 4, 17, 8, 0, 3, tzinfo=timezone.utc),
        )

        self.assertIn("ready", line)
        self.assertNotIn("projection compact", line)

    def test_turn_usage_progress_line_surfaces_live_provider_usage(self) -> None:
        line = turn_usage_progress_line(
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "context-projection",
                        "detail": "prompt_tokens=1800 token_budget=4096 source=generation",
                    }
                },
                {
                    "payload": {
                        "stage": "context-usage",
                        "detail": "prompt_tokens=720 completion_tokens=40 total_tokens=760",
                    }
                },
            )
        )

        self.assertIn("request", line)
        self.assertIn("760/4096", line)
        self.assertIn("19%", line)

    def test_terminal_failure_trace_keeps_command_visible(self) -> None:
        event = self._tool_event(
            tool_id="tool.terminal.exec",
            arguments={"command": "memo notes --help"},
            phase="execution.failed",
            detail="/bin/sh: memo: command not found",
        )

        line = tool_trace_line(None, event)

        self.assertIsNotNone(line)
        self.assertIn("memo notes --help", line or "")
        self.assertIn("[error]", line or "")

    def test_process_trace_uses_proc_label_and_action_preview(self) -> None:
        event = self._tool_event(
            tool_id="tool.process.manage",
            arguments={"action": "poll", "process_id": "proc_123"},
            phase="execution.completed",
        )

        line = tool_trace_line(None, event)

        self.assertIsNotNone(line)
        self.assertIn("🖥️", line or "")
        self.assertIn("proc", line or "")
        self.assertIn("poll proc_123", line or "")
        self.assertIn("🖥️  proc", line or "")

    def test_tool_trace_keeps_gap_after_wide_variation_emoji(self) -> None:
        cases = (
            ("tool.file.write", {"path": "notes.md"}, "✍️  write"),
            (
                "tool.process.manage",
                {"action": "poll", "process_id": "proc_123"},
                "🖥️  proc",
            ),
            ("tool.code.execute", {"code": "print('ok')"}, "🛠️  code"),
        )
        for tool_id, arguments, expected in cases:
            event = self._tool_event(
                tool_id=tool_id,
                arguments=arguments,
                phase="execution.started",
            )

            line = tool_event_progress_line(None, event)
            fragments = render_tool_trace_fragments(line or "")

            self.assertIn(expected, line or "")
            self.assertIn(
                expected.split("  ", 1)[0] + "  ",
                "".join(text for _style, text in fragments),
            )

    def test_turn_phase_cycles_marker_frames(self) -> None:
        self.assertEqual(turn_phase(0)[0], "✧")
        self.assertEqual(turn_phase(6)[0], "✦")
        self.assertEqual(turn_phase(12)[0], "✧")
        self.assertEqual(turn_phase(18)[0], "·")

    def test_live_tool_feed_lines_keep_full_trace_visible_by_default(self) -> None:
        class _Entry:
            def __init__(self, body: str) -> None:
                self.kind = "tooltrace"
                self.body = body

        class _ShellProbe:
            def __init__(self) -> None:
                self._pending_commands = []
                self._rendered_entries = 0
                self.transcript = [_Entry("\n".join(f"┊ 💻 line {index}" for index in range(20)))]

        lines = live_tool_feed_lines(_ShellProbe())

        self.assertEqual(len(lines), 20)
        self.assertIn("┊ 💻 line 0", lines)
        self.assertIn("┊ 💻 line 19", lines)
        self.assertFalse(any("earlier tool line(s) hidden" in line for line in lines))

    def test_live_tool_feed_lines_collapses_consecutive_duplicate_trace_rows(
        self,
    ) -> None:
        class _Entry:
            def __init__(self, body: str) -> None:
                self.kind = "tooltrace"
                self.body = body

        class _ShellProbe:
            def __init__(self) -> None:
                self._pending_commands = []
                self._rendered_entries = 0
                self.transcript = [
                    _Entry(
                        "\n".join(
                            (
                                "┊ 🐘 Calling model · notes…",
                                "┊ 🐘 Calling model · notes…",
                                "┊ 🐘 model        notes  0.2s",
                            )
                        )
                    )
                ]

        lines = live_tool_feed_lines(_ShellProbe())

        self.assertEqual(lines.count("┊ 🐘 Calling model · notes…"), 1)
        self.assertIn("┊ 🐘 model        notes  0.2s", lines)

    def test_queue_preview_prefers_display_command_over_full_prompt(self) -> None:
        class _ShellProbe:
            def __init__(self) -> None:
                self._pending_commands = [
                    PendingShellCommand(
                        command="summarize this\n\n[Clipboard text]\nvery long hidden body",
                        display_command="summarize this [Pasted Content 21 chars]",
                    )
                ]

            def _pad_queue_preview_line(self, content: str) -> str:
                return content

        rendered = "".join(fragment for _style, fragment in render_queued_followup_fragments(_ShellProbe()))

        self.assertIn("[Pasted Content 21 chars]", rendered)
        self.assertNotIn("very long hidden body", rendered)

    def test_progress_windows_do_not_force_fixed_heights(self) -> None:
        class _ShellProbe:
            def __init__(self) -> None:
                self._pending_commands = []

        shell = _ShellProbe()
        stream_holder = {"raw": "", "text": "streaming"}
        stream_lock = Lock()
        tool_event_holder = {"events": ()}
        tool_event_lock = Lock()
        kernel_stage_holder = {"stages": []}
        kernel_stage_lock = Lock()

        progress_window = build_turn_progress_window(
            shell,
            prompt="inspect the trace",
            started_at=0.0,
            tool_event_holder=tool_event_holder,
            tool_event_lock=tool_event_lock,
            kernel_stage_holder=kernel_stage_holder,
            kernel_stage_lock=kernel_stage_lock,
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )
        response_window = build_stream_response_window(
            shell,
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )

        self.assertIsNone(getattr(progress_window, "height", None))
        self.assertIsNone(getattr(response_window.content, "height", None))

    def test_stream_response_fragments_render_text_from_runtime_module(self) -> None:
        fragments = render_stream_response_fragments(
            None,
            stream_text="\n**hello** from streamed output",
        )

        rendered = "".join(fragment for _, fragment in fragments)
        self.assertNotIn("Elephant Agent response", rendered)
        self.assertIn("hello from streamed output", rendered)

    def test_status_bar_elapsed_fragments_surface_streaming_state(self) -> None:
        rendered = "".join(fragment for _, fragment in _status_bar_elapsed_fragments(7, streaming_active=True))
        styles = {style for style, _text in _status_bar_elapsed_fragments(7, streaming_active=True)}

        self.assertEqual(rendered, "7s · streaming")
        self.assertIn("class:status-bar-stream", styles)


if __name__ == "__main__":
    unittest.main()
