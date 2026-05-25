from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.cli.shell import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_DARK,
    BRAND_MUTED,
    Console,
    RICH_AVAILABLE,
    TranscriptEntry,
)
from apps.cli.shell_progress import (
    _VisibleToolEvent,
    latest_stream_text,
    reset_stream_text,
    stream_text_tracker,
    turn_tool_progress_lines,
)
import apps.cli.shell_progress_runtime as shell_progress_runtime
from packages.tools import ToolApprovalResult, ToolInvocation, ToolLifecycleEvent
from tests.unit.cli.shell_test_support import (
    CaptureConsole as _CaptureConsole,
    ShellTestBase,
    StubConsole as _StubConsole,
)


class ShellToolProgressTest(ShellTestBase):
    def test_turn_progress_fragments_keep_stream_text_out_of_progress_header(self) -> None:
        shell = self._make_shell()

        fragments = shell._render_turn_progress_fragments(
            prompt="draft the next release note",
            tick=0,
            stream_text="streaming chunk",
        )

        rendered = "".join(text for _style, text in fragments)
        self.assertIn("Elephant Agent is orienting", rendered)
        self.assertIn("streaming chunk", rendered)
        self.assertNotIn("active request:", rendered)

    def test_stream_text_tracker_strips_tool_markup_and_resets_between_tool_rounds(self) -> None:
        holder, lock, observer = stream_text_tracker()

        observer("I'll search for information on Xunzhuo Liu.\n")
        observer("<tool_call><invoke name=\"tool.web.search\"><parameter name=\"query\">xunzhuo")
        self.assertEqual(
            latest_stream_text(holder, lock).strip(),
            "I'll search for information on Xunzhuo Liu.",
        )

        observer(" liu researcher academic</parameter></invoke></tool_call>")
        self.assertEqual(
            latest_stream_text(holder, lock).strip(),
            "I'll search for information on Xunzhuo Liu.",
        )

        reset_stream_text(holder, lock)
        observer("I found several relevant researcher profiles.")
        self.assertEqual(
            latest_stream_text(holder, lock),
            "I found several relevant researcher profiles.",
        )

    def test_retain_stream_response_only_drops_old_thinking_but_keeps_response(self) -> None:
        holder, lock, observer = stream_text_tracker()

        observer("<think>Inspect the first result carefully.</think>I'll open the strongest profile next.")

        preserved = shell_progress_runtime.retain_stream_response_only(holder, lock)

        self.assertEqual(preserved, "I'll open the strongest profile next.")
        self.assertEqual(latest_stream_text(holder, lock), "I'll open the strongest profile next.")

    def test_tool_event_tracker_stream_anchors_exclude_historical_thinking(self) -> None:
        holder, lock, observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            stream_holder=holder,
            stream_lock=lock,
        )
        invocation = ToolInvocation(
            invocation_id="session-1:tool.web.search",
            tool_id="tool.web.search",
            session_id="session-1",
            arguments={"query": "release note"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )

        observer("<think>Inspect the strongest result first.</think>I'll open the release dashboard.")
        tool_observer(
            ToolLifecycleEvent(
                event_id="tool-event-requested-thinking-trim",
                invocation=invocation,
                phase="requested",
                detail="requested tool.web.search",
                occurred_at=invocation.requested_at,
            )
        )

        anchors = shell_progress_runtime.stream_anchor_events(tool_event_holder, tool_event_lock)

        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0].stream_text, "I'll open the release dashboard.")

    def test_boot_frame_uses_centered_full_screen_brand_layout(self) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(120)
        shell.console.size = type("Size", (), {"width": 120, "height": 34})()
        frame = shell._render_boot_frame()

        if not RICH_AVAILABLE:
            self.assertIn("Elephant Agent", str(frame))
            self.assertNotIn("waking", str(frame).lower())
            return

        panel = getattr(frame, "renderable", frame)
        self.assertIn("Elephant Agent", str(getattr(panel, "title", "")))
        self.assertNotIn("waking", str(getattr(panel, "title", "")).lower())
        self.assertEqual(str(getattr(panel, "border_style", "")), BRAND_DARK)
        self.assertEqual(getattr(panel, "width", None), 72)
        console = Console(width=120, record=True, force_terminal=True)
        console.print(frame)
        rendered = console.export_text(styles=False)
        self.assertNotIn("ELEPHANT // wake", rendered)
        self.assertNotIn("waking", rendered.lower())
        self.assertIn("Picking up your thread", rendered)
        self.assertIn("Evidence I", rendered)

    def test_startup_sequence_does_not_render_boot_animation(self) -> None:
        shell = self._make_shell()
        with mock.patch.object(shell, "_render_boot_frame") as render_boot:
            shell._render_startup_sequence()
        render_boot.assert_not_called()

    def test_unknown_command_uses_brand_accent_panel(self) -> None:
        shell = self._make_shell()
        panel = shell._render_entry(TranscriptEntry(kind="command", title="Unknown command", body="/wat\nhelp: /help"))
        self.assertEqual(getattr(panel, "title", ""), "Unknown command")
        border_style = getattr(panel, "border_style", None)
        if border_style is not None:
            self.assertEqual(str(border_style), BRAND_ACCENT)

    def test_personal_model_update_progress_copy_mentions_understanding_surface(self) -> None:
        shell = self._make_shell()
        event = ToolLifecycleEvent(
            event_id="tool-event-2",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.personal_model.update",
                tool_id="tool.personal_model.update",
                session_id="session-1",
                arguments={"action": "remember", "lens": "trait", "topic": "identity.name.preferred", "text": "The user's preferred name is Bit."},
            ),
            phase="execution.started",
            detail="executing tool.personal_model.update",
            approval=ToolApprovalResult(
                decision="approved",
                risk_class="medium",
                reason="auto-approved locally",
            ),
        )

        title, detail = shell._tool_event_lines(event)
        self.assertEqual(title, "Tool executing · tool.personal_model.update")
        self.assertIn("executing tool.personal_model.update", detail or "")

        frame = shell._render_tool_frame(tool_id="tool.personal_model.update", tick=3, tool_event=event)
        renderable = getattr(frame, "renderable", frame)
        rendered = renderable.plain if hasattr(renderable, "plain") else str(renderable)
        self.assertIn("┊ 🌱 learn", rendered)
        self.assertIn("remember identity.name.preferred", rendered)

    def test_personal_model_search_progress_uses_generic_lookup_copy(self) -> None:
        shell = self._make_shell()
        event = ToolLifecycleEvent(
            event_id="tool-event-2c",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.personal_model.search",
                tool_id="tool.personal_model.search",
                session_id="session-1",
                arguments={"query": "notes"},
            ),
            phase="execution.started",
            detail="executing tool.personal_model.search",
        )

        title, detail = shell._tool_event_lines(event)
        self.assertEqual(title, "Tool executing · tool.personal_model.search")
        self.assertIn("executing tool.personal_model.search", detail or "")

        frame = shell._render_tool_frame(tool_id="tool.personal_model.search", tick=2, tool_event=event)
        renderable = getattr(frame, "renderable", frame)
        rendered = renderable.plain if hasattr(renderable, "plain") else str(renderable)
        self.assertIn("┊ 🐘 model", rendered)

    def test_tool_trace_lines_persist_start_and_completion_events(self) -> None:
        shell = self._make_shell()
        started_at = datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc)
        requested = ToolLifecycleEvent(
            event_id="tool-event-requested",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.file.search",
                tool_id="tool.file.search",
                session_id="session-1",
                arguments={"query": "xunzhuo liu"},
                requested_at=started_at,
            ),
            phase="requested",
            detail="requested tool.file.search",
            occurred_at=started_at,
        )
        completed = ToolLifecycleEvent(
            event_id="tool-event-completed",
            invocation=requested.invocation,
            phase="execution.completed",
            detail="completed tool.file.search",
            occurred_at=started_at.replace(second=3, microsecond=200000),
        )

        shell._record_tool_event_trace(requested)
        shell._record_tool_event_trace(completed)

        tool_entries = [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn("┊ 🔎 Calling grep · xunzhuo liu…", tool_entries[0].body)
        self.assertIn("┊ 🔎 grep", tool_entries[0].body)
        self.assertIn("xunzhuo liu", tool_entries[0].body)
        self.assertIn("3.2s", tool_entries[0].body)

    def test_todo_completed_event_appends_current_items_to_tooltrace(self) -> None:
        shell = self._make_shell()
        shell.runtime.todo_store.upsert_item(
            shell.session_id,
            title="梳理 UI 工具链路",
            status="in_progress",
            notes="",
        )
        shell.runtime.todo_store.upsert_item(
            shell.session_id,
            title="补齐 write file diff 预览",
            status="open",
            notes="",
        )
        event = ToolLifecycleEvent(
            event_id="tool-event-todo-completed",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.todo.manage",
                tool_id="tool.todo.manage",
                session_id=shell.session_id,
                arguments={"action": "list"},
                requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
            ),
            phase="execution.completed",
            detail="listed todos",
            execution=SimpleNamespace(outcome="success"),
        )

        shell._record_tool_event_trace(event)

        tool_entries = [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn("┊ 📋 todo", tool_entries[0].body)
        self.assertIn("┊ 📋 todo items   2 item(s)", tool_entries[0].body)
        self.assertIn("in_progress | 梳理 UI 工具链路", tool_entries[0].body)
        self.assertIn("open | 补齐 write file diff 预览", tool_entries[0].body)

    def test_file_write_completed_event_appends_review_diff_to_tooltrace(self) -> None:
        shell = self._make_shell()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            file_path = Path(tmpdir) / "tool-review-diff.md"
            file_path.write_text("hello\n", encoding="utf-8")
            relative_path = str(file_path.relative_to(Path.cwd()))
            requested_at = datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc)
            invocation = ToolInvocation(
                invocation_id="session-1:tool.file.write",
                tool_id="tool.file.write",
                session_id=shell.session_id,
                arguments={"path": relative_path, "content": "hello\nworld\n"},
                requested_at=requested_at,
            )
            requested = ToolLifecycleEvent(
                event_id="tool-event-write-requested",
                invocation=invocation,
                phase="requested",
                detail="requested tool.file.write",
                occurred_at=requested_at,
            )
            completed = ToolLifecycleEvent(
                event_id="tool-event-write-completed",
                invocation=invocation,
                phase="execution.completed",
                detail=f"path: {relative_path}",
                execution=SimpleNamespace(outcome="success"),
                occurred_at=requested_at.replace(second=1),
            )

            shell._record_tool_event_trace(requested)
            file_path.write_text("hello\nworld\n", encoding="utf-8")
            shell._record_tool_event_trace(completed)

        tool_entries = [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn("┊ ✍️  write", tool_entries[0].body)
        self.assertIn("┊ ✍️ diff", tool_entries[0].body)
        self.assertIn(f"a/{relative_path} → b/{relative_path}", tool_entries[0].body)
        self.assertIn("@@ -1 +1,2 @@", tool_entries[0].body)
        self.assertIn("+world", tool_entries[0].body)

    def test_turn_tool_progress_lines_keep_write_visible_when_diff_is_pending(self) -> None:
        shell = self._make_shell()
        shell.transcript = [
            TranscriptEntry(
                kind="tooltrace",
                title="Tool trace",
                body=(
                    "┊ 🛠 Calling write…\n"
                    "┊ 🛠 write        notes.md  0.2s\n"
                    "┊ 🛠 diff\n"
                    "a/notes.md → b/notes.md\n"
                    "@@ -1 +1,2 @@\n"
                    " hello\n"
                    "+world"
                ),
            )
        ]
        shell._rendered_entries = 0

        lines = turn_tool_progress_lines(shell)

        self.assertIn("┊ 🛠 Calling write…", lines)
        self.assertIn("┊ 🛠 write        notes.md  0.2s", lines)
        self.assertIn("┊ 🛠 diff", lines)
        self.assertFalse(any(line.startswith("a/") for line in lines))
        self.assertFalse(any(line.startswith("@@") for line in lines))
        self.assertFalse(any(line.startswith("+") for line in lines))

    def test_render_pending_entries_leaves_context_compaction_for_outcome_notice(self) -> None:
        shell = self._make_shell()
        shell._pending_context_compaction_frame = {
            "prompt": "hello",
            "tick": 0,
            "kernel_stage_events": (
                {
                    "payload": {
                        "stage": "context-compact",
                        "detail": "reason=usage tokens=1800->620 messages=80->12 compacted_messages=68 tail=10",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    }
                },
            ),
        }
        if RICH_AVAILABLE:
            shell.console = Console(width=100, record=True, force_terminal=True)
            shell._render_pending_entries()
            rendered = shell.console.export_text(styles=False)
        else:
            capture = _CaptureConsole(100)
            shell.console = capture
            shell._render_pending_entries()
            rendered = "\n".join(capture.printed)

        self.assertFalse(shell._pending_context_compaction_frame_rendered)
        self.assertNotIn("🧩 context", rendered)
        self.assertIsNotNone(shell._pending_context_compaction_frame)

    def test_turn_progress_frame_keeps_later_tool_events_visible_after_diff_body(self) -> None:
        shell = self._make_shell()
        shell.transcript = [
            TranscriptEntry(
                kind="tooltrace",
                title="Tool trace",
                body=(
                    "┊ 🛠 write        notes.md  0.2s\n"
                    "┊ 🛠 diff\n"
                    "a/notes.md → b/notes.md\n"
                    "@@ -1 +1,2 @@\n"
                    " hello\n"
                    "+world\n"
                    "┊ 💻 computer     osascript -e 'tell app \"Notes\" to activate'  0.3s"
                ),
            )
        ]
        shell._rendered_entries = 0

        frame = shell._render_turn_frame(prompt="hello", tick=0)
        renderable = getattr(frame, "renderable", frame)
        rendered = renderable.plain if hasattr(renderable, "plain") else str(renderable)

        self.assertIn("┊ 🛠 diff", rendered)
        self.assertIn("a/notes.md → b/notes.md", rendered)
        self.assertIn("┊ 💻 computer", rendered)
        self.assertIn("osascript", rendered)

    def test_personal_model_update_completed_event_keeps_generic_tooltrace(self) -> None:
        shell = self._make_shell()
        event = ToolLifecycleEvent(
            event_id="tool-event-state-completed",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.personal_model.update",
                tool_id="tool.personal_model.update",
                session_id=shell.session_id,
                arguments={"action": "remember", "lens": "trait", "topic": "identity.name.preferred", "text": "The user's preferred name is Bit."},
                requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
            ),
            phase="execution.completed",
            detail="understanding updated",
            execution=SimpleNamespace(outcome="success"),
        )

        shell._record_tool_event_trace(event)

        tool_entries = [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn("┊ 🌱 learn", tool_entries[0].body)
        self.assertIn("remember identity.name.preferred", tool_entries[0].body)
        self.assertNotIn("legacy file", tool_entries[0].body.lower())

    def test_tool_trace_entries_render_with_layered_styles(self) -> None:
        shell = self._make_shell()
        rendered = shell._render_entry(
            TranscriptEntry(
                kind="tooltrace",
                title="Tool trace",
                body="┊ 🌐 search       xunzhuo liu  3.2s",
            )
        )

        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        self.assertIn("┊ 🌐 search", plain)
        self.assertIn("xunzhuo liu", plain)
        self.assertIn("3.2s", plain)
        if RICH_AVAILABLE:
            styles = {str(span.style) for span in rendered.spans}
            self.assertIn(BRAND_DARK, styles)
            self.assertIn(BRAND_ACCENT, styles)
            self.assertIn(BRAND_MUTED, styles)
            self.assertIn(f"bold {BRAND_ACCENT_STRONG}", styles)

    def test_turn_progress_fragments_reuse_tool_trace_copy_for_live_events(self) -> None:
        shell = self._make_shell()
        invocation = ToolInvocation(
            invocation_id="session-1:tool.web.search",
            tool_id="tool.web.search",
            session_id="session-1",
            arguments={"query": "xunzhuo liu"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )
        requested = ToolLifecycleEvent(
            event_id="tool-event-requested",
            invocation=invocation,
            phase="requested",
            detail="requested tool.web.search",
            occurred_at=invocation.requested_at,
        )
        started = ToolLifecycleEvent(
            event_id="tool-event-started",
            invocation=invocation,
            phase="execution.started",
            detail="executing tool.web.search",
            occurred_at=invocation.requested_at,
        )

        requested_fragments = shell._render_turn_progress_fragments(prompt="search xunzhuo liu", tick=0, tool_event=requested)
        started_fragments = shell._render_turn_progress_fragments(prompt="search xunzhuo liu", tick=0, tool_event=started)

        requested_text = "".join(fragment[1] for fragment in requested_fragments)
        started_text = "".join(fragment[1] for fragment in started_fragments)
        self.assertIn("┊ 🌐 Calling search", requested_text)
        self.assertIn("┊ 🌐 search", started_text)
        self.assertIn("xunzhuo liu", started_text)

    def test_turn_progress_fragments_anchor_stream_text_to_matching_tool_event(self) -> None:
        shell = self._make_shell()
        stream_holder, stream_lock, stream_observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )
        search_invocation = ToolInvocation(
            invocation_id="session-1:tool.web.search",
            tool_id="tool.web.search",
            session_id="session-1",
            arguments={"query": "xunzhuo liu"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )
        search_requested = ToolLifecycleEvent(
            event_id="tool-event-search-requested",
            invocation=search_invocation,
            phase="requested",
            detail="requested tool.web.search",
            occurred_at=search_invocation.requested_at,
        )
        search_started = ToolLifecycleEvent(
            event_id="tool-event-search-started",
            invocation=search_invocation,
            phase="execution.started",
            detail="executing tool.web.search",
            occurred_at=search_invocation.requested_at,
        )
        read_invocation = ToolInvocation(
            invocation_id="session-1:tool.web.read",
            tool_id="tool.web.read",
            session_id="session-1",
            arguments={"url": "https://example.com/profile"},
            requested_at=datetime(2026, 4, 13, 8, 0, 1, tzinfo=timezone.utc),
        )
        read_requested = ToolLifecycleEvent(
            event_id="tool-event-read-requested",
            invocation=read_invocation,
            phase="requested",
            detail="requested tool.web.read",
            occurred_at=read_invocation.requested_at,
        )
        read_started = ToolLifecycleEvent(
            event_id="tool-event-read-started",
            invocation=read_invocation,
            phase="execution.started",
            detail="executing tool.web.read",
            occurred_at=read_invocation.requested_at,
        )

        stream_observer("I'll search for the profile first.")
        tool_observer(search_requested)
        tool_observer(search_started)
        stream_observer("\nThen I'll open the best result.")
        tool_observer(read_requested)
        tool_observer(read_started)

        fragments = shell_progress_runtime.render_turn_progress_fragments(
            shell,
            prompt="inspect the profile",
            tick=0,
            stream_text=latest_stream_text(stream_holder, stream_lock),
            tool_event_holder=tool_event_holder,
            tool_event_lock=tool_event_lock,
        )

        rendered = "".join(fragment[1] for fragment in fragments)
        self.assertLess(rendered.index("I'll search for the profile first."), rendered.index("┊ 🌐 search"))
        self.assertGreater(rendered.index("Then I'll open the best result."), rendered.index("┊ 🌐 search"))
        self.assertLess(rendered.index("Then I'll open the best result."), rendered.rindex("Calling fetch"))

    def test_turn_progress_fragments_keep_stream_text_with_started_event_after_requested_event_expires(self) -> None:
        shell = self._make_shell()
        stream_holder, stream_lock, stream_observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )
        invocation = ToolInvocation(
            invocation_id="session-1:tool.web.search",
            tool_id="tool.web.search",
            session_id="session-1",
            arguments={"query": "elephant status"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )
        requested = ToolLifecycleEvent(
            event_id="tool-event-requested",
            invocation=invocation,
            phase="requested",
            detail="requested tool.web.search",
            occurred_at=invocation.requested_at,
        )
        started = ToolLifecycleEvent(
            event_id="tool-event-started",
            invocation=invocation,
            phase="execution.started",
            detail="executing tool.web.search",
            occurred_at=invocation.requested_at,
        )

        stream_observer("I'll inspect local files first.")
        tool_observer(requested)
        tool_observer(started)

        now = time.monotonic()
        with tool_event_lock:
            tool_event_holder["feed"] = [
                _VisibleToolEvent(
                    event=item.event,
                    expires_at=(now - 1.0) if item.event.phase == "requested" else (now + 10.0),
                    stream_text=item.stream_text,
                )
                for item in tool_event_holder.get("feed", ())
                if isinstance(item, _VisibleToolEvent)
            ]

        fragments = shell_progress_runtime.render_turn_progress_fragments(
            shell,
            prompt="inspect local files",
            tick=0,
            stream_text=latest_stream_text(stream_holder, stream_lock),
            tool_event_holder=tool_event_holder,
            tool_event_lock=tool_event_lock,
        )

        rendered = "".join(fragment[1] for fragment in fragments)
        self.assertIn("I'll inspect local files first.", rendered)
        self.assertEqual(rendered.count("I'll inspect local files first."), 1)
        self.assertLess(rendered.index("I'll inspect local files first."), rendered.index("┊ 🌐 search"))

    def test_turn_progress_fragments_preserve_repeated_tool_rail_with_late_stream_anchor(self) -> None:
        shell = self._make_shell()
        shell._rendered_entries = len(shell.transcript)
        stream_holder, stream_lock, stream_observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            shell._record_tool_event_trace,
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )
        first_invocation = ToolInvocation(
            invocation_id="session-1:tool.file.read:1",
            tool_id="tool.file.read",
            session_id="session-1",
            arguments={"file_path": "/tmp/alpha.txt"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )
        first_requested = ToolLifecycleEvent(
            event_id="tool-event-read-requested-1",
            invocation=first_invocation,
            phase="requested",
            detail="requested tool.file.read",
            occurred_at=first_invocation.requested_at,
        )
        first_completed = ToolLifecycleEvent(
            event_id="tool-event-read-completed-1",
            invocation=first_invocation,
            phase="execution.completed",
            detail="read /tmp/alpha.txt",
            occurred_at=datetime(2026, 4, 13, 8, 0, 0, 700000, tzinfo=timezone.utc),
            execution=SimpleNamespace(outcome="success"),
        )
        second_invocation = ToolInvocation(
            invocation_id="session-1:tool.file.read:2",
            tool_id="tool.file.read",
            session_id="session-1",
            arguments={"file_path": "/tmp/beta.txt"},
            requested_at=datetime(2026, 4, 13, 8, 0, 1, tzinfo=timezone.utc),
        )
        second_requested = ToolLifecycleEvent(
            event_id="tool-event-read-requested-2",
            invocation=second_invocation,
            phase="requested",
            detail="requested tool.file.read",
            occurred_at=second_invocation.requested_at,
        )

        stream_observer("I'll inspect the first file.")
        tool_observer(first_requested)
        tool_observer(first_completed)
        stream_observer("\nThen I'll inspect the second file.")
        tool_observer(second_requested)

        fragments = shell_progress_runtime.render_turn_progress_fragments(
            shell,
            prompt="inspect files",
            tick=0,
            stream_text=latest_stream_text(stream_holder, stream_lock),
            tool_event_holder=tool_event_holder,
            tool_event_lock=tool_event_lock,
        )

        rendered = "".join(fragment[1] for fragment in fragments)
        self.assertGreaterEqual(rendered.count("Calling read"), 2)
        self.assertIn("┊ 📖 read         /tmp/alpha.txt  0.7s", rendered)
        self.assertLess(rendered.index("┊ 📖 read         /tmp/alpha.txt  0.7s"), rendered.index("Then I'll inspect the second file."))
        self.assertLess(rendered.index("Then I'll inspect the second file."), rendered.rindex("Calling read"))

    def test_turn_progress_fragments_keep_middle_stream_text_after_live_events_expire(self) -> None:
        shell = self._make_shell()
        shell._rendered_entries = len(shell.transcript)
        stream_holder, stream_lock, stream_observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            shell._record_tool_event_trace,
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )
        search_invocation = ToolInvocation(
            invocation_id="session-1:tool.web.search",
            tool_id="tool.web.search",
            session_id="session-1",
            arguments={"query": "xunzhuo liu"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )
        search_requested = ToolLifecycleEvent(
            event_id="tool-event-search-requested-expiring",
            invocation=search_invocation,
            phase="requested",
            detail="requested tool.web.search",
            occurred_at=search_invocation.requested_at,
        )
        search_completed = ToolLifecycleEvent(
            event_id="tool-event-search-completed-expiring",
            invocation=search_invocation,
            phase="execution.completed",
            detail="completed tool.web.search",
            occurred_at=datetime(2026, 4, 13, 8, 0, 0, 900000, tzinfo=timezone.utc),
            execution=SimpleNamespace(outcome="success"),
        )
        read_invocation = ToolInvocation(
            invocation_id="session-1:tool.web.read",
            tool_id="tool.web.read",
            session_id="session-1",
            arguments={"url": "https://example.com/profile"},
            requested_at=datetime(2026, 4, 13, 8, 0, 1, tzinfo=timezone.utc),
        )
        read_requested = ToolLifecycleEvent(
            event_id="tool-event-read-requested-expiring",
            invocation=read_invocation,
            phase="requested",
            detail="requested tool.web.read",
            occurred_at=read_invocation.requested_at,
        )

        stream_observer("I'll search for the profile first.")
        tool_observer(search_requested)
        tool_observer(search_completed)
        stream_observer("\nThen I'll open the best result.")
        tool_observer(read_requested)

        now = time.monotonic()
        with tool_event_lock:
            tool_event_holder["feed"] = [
                _VisibleToolEvent(event=item.event, expires_at=now - 1.0, stream_text=item.stream_text)
                for item in tool_event_holder.get("feed", ())
                if isinstance(item, _VisibleToolEvent)
            ]

        fragments = shell_progress_runtime.render_turn_progress_fragments(
            shell,
            prompt="inspect the profile",
            tick=0,
            stream_text=latest_stream_text(stream_holder, stream_lock),
            tool_event_holder=tool_event_holder,
            tool_event_lock=tool_event_lock,
        )

        rendered = "".join(fragment[1] for fragment in fragments)
        self.assertLess(rendered.index("I'll search for the profile first."), rendered.index("Calling search"))
        self.assertGreater(rendered.index("Then I'll open the best result."), rendered.index("┊ 🌐 search"))
        self.assertLess(rendered.index("Then I'll open the best result."), rendered.rindex("Calling fetch"))

    def test_turn_progress_fragments_keep_earliest_stream_anchor_after_live_feed_truncates(self) -> None:
        shell = self._make_shell()
        shell._rendered_entries = len(shell.transcript)
        stream_holder, stream_lock, stream_observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            shell._record_tool_event_trace,
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )
        invocations_and_events = (
            (
                "I'll search first.",
                ToolInvocation(
                    invocation_id="session-1:tool.web.search",
                    tool_id="tool.web.search",
                    session_id="session-1",
                    arguments={"query": "alpha"},
                    requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
                ),
                "requested tool.web.search",
                "completed tool.web.search",
                datetime(2026, 4, 13, 8, 0, 0, 500000, tzinfo=timezone.utc),
            ),
            (
                "\nThen I'll fetch.",
                ToolInvocation(
                    invocation_id="session-1:tool.web.read",
                    tool_id="tool.web.read",
                    session_id="session-1",
                    arguments={"url": "https://example.com/alpha"},
                    requested_at=datetime(2026, 4, 13, 8, 0, 1, tzinfo=timezone.utc),
                ),
                "requested tool.web.read",
                "completed tool.web.read",
                datetime(2026, 4, 13, 8, 0, 1, 500000, tzinfo=timezone.utc),
            ),
            (
                "\nNext I'll read a file.",
                ToolInvocation(
                    invocation_id="session-1:tool.file.read",
                    tool_id="tool.file.read",
                    session_id="session-1",
                    arguments={"file_path": "/tmp/alpha.txt"},
                    requested_at=datetime(2026, 4, 13, 8, 0, 2, tzinfo=timezone.utc),
                ),
                "requested tool.file.read",
                "read /tmp/alpha.txt",
                datetime(2026, 4, 13, 8, 0, 2, 500000, tzinfo=timezone.utc),
            ),
            (
                "\nFinally I'll grep.",
                ToolInvocation(
                    invocation_id="session-1:tool.file.search",
                    tool_id="tool.file.search",
                    session_id="session-1",
                    arguments={"query": "needle"},
                    requested_at=datetime(2026, 4, 13, 8, 0, 3, tzinfo=timezone.utc),
                ),
                "requested tool.file.search",
                "completed tool.file.search",
                datetime(2026, 4, 13, 8, 0, 3, 500000, tzinfo=timezone.utc),
            ),
        )

        for message, invocation, requested_detail, completed_detail, completed_at in invocations_and_events:
            stream_observer(message)
            tool_observer(
                ToolLifecycleEvent(
                    event_id=f"{invocation.invocation_id}:requested",
                    invocation=invocation,
                    phase="requested",
                    detail=requested_detail,
                    occurred_at=invocation.requested_at,
                )
            )
            tool_observer(
                ToolLifecycleEvent(
                    event_id=f"{invocation.invocation_id}:completed",
                    invocation=invocation,
                    phase="execution.completed",
                    detail=completed_detail,
                    occurred_at=completed_at,
                    execution=SimpleNamespace(outcome="success"),
                )
            )

        with tool_event_lock:
            feed = [item for item in tool_event_holder.get("feed", ()) if isinstance(item, _VisibleToolEvent)]
            self.assertEqual(len(feed), 6)
            self.assertNotIn("session-1:tool.web.search", {item.event.invocation.invocation_id for item in feed})

        fragments = shell_progress_runtime.render_turn_progress_fragments(
            shell,
            prompt="inspect the profile",
            tick=0,
            stream_text=latest_stream_text(stream_holder, stream_lock),
            tool_event_holder=tool_event_holder,
            tool_event_lock=tool_event_lock,
        )

        rendered = "".join(fragment[1] for fragment in fragments)
        self.assertLess(rendered.index("I'll search first."), rendered.index("Calling search"))
        self.assertLess(rendered.index("Then I'll fetch."), rendered.index("Calling fetch"))
        self.assertLess(rendered.index("Next I'll read a file."), rendered.index("Calling read"))
        self.assertLess(rendered.index("Finally I'll grep."), rendered.index("Calling grep"))


if __name__ == "__main__":
    unittest.main()
