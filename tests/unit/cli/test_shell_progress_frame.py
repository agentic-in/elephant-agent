from __future__ import annotations

import unittest

from apps.cli.shell import Console, RICH_AVAILABLE
from packages.tools import ToolApprovalResult, ToolInvocation, ToolLifecycleEvent
from tests.unit.cli.shell_test_support import ShellTestBase


class ShellProgressFrameTest(ShellTestBase):
    def test_turn_progress_frame_uses_growing_copy(self) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(prompt="hello", tick=0)
        if RICH_AVAILABLE:
            self.assertIn(
                "Elephant Agent is orienting", str(getattr(frame, "title", ""))
            )
        else:
            self.assertIn("Checking conversation context", str(frame))

    def test_turn_progress_title_rotates_with_tick(self) -> None:
        shell = self._make_shell()

        first = shell._render_turn_frame(prompt="hello", tick=0)
        # Title rotates once every 32 render ticks (~2.5s at 12.5 Hz).
        # Jump well past that boundary to see the second stage.
        later = shell._render_turn_frame(prompt="hello", tick=64)

        if RICH_AVAILABLE:
            self.assertIn(
                "Elephant Agent is orienting", str(getattr(first, "title", ""))
            )
            self.assertIn(
                "Elephant Agent is listening", str(getattr(later, "title", ""))
            )
        else:
            self.assertIn("Checking conversation context", str(first))
            self.assertIn("Composing the reply", str(later))

    def test_turn_progress_frame_surfaces_live_tool_activity(self) -> None:
        shell = self._make_shell()
        event = ToolLifecycleEvent(
            event_id="tool-event-1",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.web.read",
                tool_id="tool.web.read",
                session_id="session-1",
                arguments={"url": "https://example.com"},
            ),
            phase="execution.started",
            detail="executing tool.web.read",
            approval=ToolApprovalResult(
                decision="approved",
                risk_class="high",
                required_controls=("outbound-policy",),
                reason="auto-approved locally",
            ),
        )
        frame = shell._render_turn_frame(prompt="hello", tick=0, tool_event=event)
        renderable = getattr(frame, "renderable", frame)
        rendered = renderable.plain if hasattr(renderable, "plain") else str(renderable)
        self.assertIn("┊ 🌐 fetch", rendered)
        self.assertIn("https://example.com", rendered)

    def test_turn_progress_frame_keeps_cumulative_tool_rail_visible(self) -> None:
        shell = self._make_shell()
        shell._rendered_entries = len(shell.transcript)
        shell._append_tooltrace_line("┊ 📚 Calling skill…")
        shell._append_tooltrace_line("┊ 📚 skill        apple-notes  0.3s")
        event = ToolLifecycleEvent(
            event_id="tool-event-2",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.terminal.exec",
                tool_id="tool.terminal.exec",
                session_id="session-1",
                arguments={"command": "memo notes --help"},
            ),
            phase="execution.started",
            detail="executing tool.terminal.exec",
        )

        frame = shell._render_turn_frame(prompt="hello", tick=0, tool_event=event)
        renderable = getattr(frame, "renderable", frame)
        rendered = renderable.plain if hasattr(renderable, "plain") else str(renderable)

        self.assertIn("Calling skill", rendered)
        self.assertIn("apple-notes", rendered)
        self.assertIn("memo notes --help", rendered)

    def test_turn_progress_frame_renders_streaming_response_in_dedicated_surface(
        self,
    ) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(
            prompt="hello",
            tick=0,
            stream_text="First line of the reply.\nSecond line arrives next.",
        )

        if RICH_AVAILABLE:
            console = Console(width=100, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(frame)

        self.assertNotIn("Elephant Agent response", rendered)
        self.assertIn("First line of the reply.", rendered)
        self.assertIn("Second line arrives next.", rendered)

    def test_turn_progress_frame_formats_reasoning_with_elephant_mind_heading(
        self,
    ) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(
            prompt="hello",
            tick=0,
            stream_text="<think>Inspect the tool results first.</think>The release note draft is ready.",
        )

        if RICH_AVAILABLE:
            console = Console(width=100, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(frame)

        normalized_lines = [line.strip("│ ").rstrip() for line in rendered.splitlines()]
        mind_index = normalized_lines.index("🐾 Elephant Agent's Trail:")

        self.assertEqual(
            normalized_lines[mind_index + 1], "Inspect the tool results first."
        )
        self.assertEqual(normalized_lines[mind_index + 2], "")
        # Streaming frames decorate the tail with a pulsing cursor glyph
        # (▌▍▎▏). Be robust to that decoration — the response prefix should
        # still match exactly.
        self.assertTrue(
            normalized_lines[mind_index + 3].startswith(
                "The release note draft is ready."
            ),
            normalized_lines[mind_index + 3],
        )

    def test_turn_progress_frame_surfaces_context_compaction(self) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(
            prompt="hello",
            tick=0,
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "context-compact",
                        "detail": "reason=usage tokens=1800->620 messages=80->12 compacted_messages=68 tail=10",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    }
                },
            ),
        )

        if RICH_AVAILABLE:
            console = Console(width=100, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(frame)

        self.assertIn("🧩 context", rendered)
        self.assertIn("projection compact", rendered)
        self.assertIn("est 1800->620 tokens", rendered)

    def test_turn_progress_frame_surfaces_recall_without_context_ready_or_request_rows(
        self,
    ) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(
            prompt="hello",
            tick=0,
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "context",
                        "detail": "bundle=bundle:session budget=204800",
                    }
                },
                {
                    "payload": {
                        "stage": "context-projection",
                        "detail": "prompt_tokens=2534 token_budget=204800 source=generation",
                    }
                },
                {
                    "payload": {
                        "stage": "recall",
                        "detail": "status=hit count=2 bytes=128",
                    }
                },
            ),
        )

        if RICH_AVAILABLE:
            console = Console(width=100, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(frame)

        self.assertIn("🗺️ recall", rendered)
        self.assertIn("linked 2 signals", rendered)
        self.assertNotIn("🧩 context", rendered)
        self.assertNotIn("📈 request", rendered)
        self.assertNotIn("provider running", rendered)

    def test_turn_progress_frame_hides_raw_tool_call_markup_from_stream_response(
        self,
    ) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(
            prompt="hello",
            tick=0,
            stream_text=(
                "I'll search for information on Xunzhuo Liu.\n"
                '<tool_call><invoke name="tool.web.search"><parameter name="query">'
                "xunzhuo liu researcher academic</parameter></invoke></tool_call>"
            ),
        )

        if RICH_AVAILABLE:
            console = Console(width=100, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(frame)

        self.assertIn("I'll search for information on Xunzhuo Liu.", rendered)
        self.assertNotIn("<tool_call>", rendered)
        self.assertNotIn("<invoke name=", rendered)
        self.assertNotIn("<parameter name=", rendered)


if __name__ == "__main__":
    unittest.main()
