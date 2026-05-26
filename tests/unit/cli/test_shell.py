from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from queue import Queue
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.cli.runtime import CliRuntime
from apps.cli.shell_composer import (
    _state_focus_notice_fragments,
    _startup_transition_result,
    build_composer_body,
    prompt_style_map,
)
from apps.cli.shell_progress import (
    _VisibleToolEvent,
    latest_stream_text,
    reset_stream_text,
    stream_text_tracker,
    turn_tool_progress_lines,
)
import apps.cli.shell_progress_runtime as shell_progress_runtime
from apps.cli.shell_render import _render_tooltrace_body_line
import apps.cli.shell_render as shell_render
from apps.cli.shell_banner import (
    _learning_job_execution_summary,
    _skill_affinity_summary,
)
import apps.cli.shell_progress_trace as shell_progress_trace
from apps.cli.shell_clarify import (
    ShellClarifyState,
    render_clarify_fragments,
    route_clarify_answer,
)
from apps.cli.shell_stack import (
    FormattedTextControl as StackFormattedTextControl,
    ScrollablePane,
    Window as StackWindow,
)
from apps.cli.shell import (
    BRAND_ACCENT,
    BRAND_DARK,
    BRAND_LIGHT,
    BRAND_MUTED,
    BRAND_ACCENT_STRONG,
    COMMAND_PALETTE_VISIBLE_ROWS,
    Console,
    Document,
    ELEPHANT_STAGE_ROWS,
    ELEPHANT_STAGE_ROWS,
    GROWTH_PROGRESS_EMPTY,
    GROWTH_PROGRESS_FILLED,
    GROWTH_PROGRESS_WIDTH,
    GROWTH_HIGHLIGHT_FG,
    HATCHLING_STAGE_ROWS,
    HATCHLING_HEAD_ROWS,
    PendingShellCommand,
    QUEUE_PREVIEW_INSET,
    SCOUT_STAGE_ROWS,
    SEED_STAGE_ROWS,
    SHELL_WELCOME_HEADLINE,
    STARTUP_SEQUENCE_FINAL_DELAY,
    STARTUP_SEQUENCE_STEP_DELAY,
    USER_HISTORY_BG,
    USER_HISTORY_FG,
    _centered_elephant_rows,
    ProductizedShell,
    RICH_AVAILABLE,
    ShellCompleter,
    TranscriptEntry,
    _display_width,
)
from apps.cli.wizard import WIZARD_BACK
from apps.cli.shell_ui import (
    GROWTH_MARK_CANVAS_WIDTH,
    LIVE_DIFF_ADD_FG,
    LIVE_DIFF_FILE_FG,
    LIVE_DIFF_HUNK_FG,
    LIVE_DIFF_REMOVE_FG,
    SETTLED_DIFF_ADD_FG,
    SETTLED_DIFF_FILE_FG,
    SETTLED_DIFF_HUNK_FG,
    SETTLED_DIFF_REMOVE_FG,
    visual_centered_rows,
)
from packages.contracts import (
    ContextBundle,
    EventEnvelope,
    ExecutionResult,
    Fact,
    OpenQuestion,
    StateFocusReason,
    PromptEnvelope,
)
from packages.contracts.runtime import StateFocusDecision
from packages.growth import GrowthTurnSignals, apply_turn_growth, default_growth_state
from packages.state import render_user_profile_text
from packages.skills import SkillSearchEntry
from packages.tools import ToolApprovalResult, ToolLifecycleEvent, ToolInvocation
from tests.unit.cli.shell_test_support import (
    CaptureConsole as _CaptureConsole,
    ShellTestBase,
    StubConsole as _StubConsole,
    WebPageStubServer as _WebPageStubServer,
)


class ShellPaletteTest(ShellTestBase):
    def test_work_surface_discloses_resolved_state_focus_scope_and_fallback(
        self,
    ) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        profile = shell.runtime.inspect_profile(session.personal_model_id)

        shell.runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=shell.runtime.inspect_recall_evidence(shell.session_id),
            plan=None,
            execution=None,
            delivery=None,
            stages=(),
            event=None,
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=StateFocusDecision(
                focus_family="resume",
                confidence=0.92,
                focus_work_item_ids=("state-focus:operator-rollout",),
                continuity_signal="continue",
                focus_scope="lineage",
                context_budget="narrow",
                embedding_available=False,
                degradation_mode="embedding-unavailable",
                needs_focus_model_assist=True,
                focus_assist_outcome="suggested",
                selection_path="embedding-unavailable.weak-assist.suggested.narrow",
                reasons=(
                    StateFocusReason(
                        "continuation",
                        "The prompt continues the active rollout thread.",
                        0.9,
                    ),
                    StateFocusReason(
                        "focus", "The active work stays ahead of generic recall.", 0.8
                    ),
                ),
                audit_trace=(
                    "stage3: fallback path -> embedding-unavailable.weak-assist.suggested.narrow",
                ),
            ),
        )

        self.assertFalse(hasattr(shell, "_append_work"))
        self.assertFalse(shell._handle_slash_command("/work"))
        self.assertEqual(shell.transcript[-1].title, "Unknown command")

    def test_conversational_surface_requests_can_schedule_prompt_cron_and_list_jobs(
        self,
    ) -> None:
        shell = self._make_shell()

        created = shell._handle_conversational_surface_request(
            "schedule a prompt to tell me a joke every morning"
        )
        listed = shell._handle_conversational_surface_request(
            "what cron jobs do you have?"
        )

        self.assertTrue(created)
        self.assertTrue(listed)
        self.assertEqual(shell.transcript[-2].kind, "assistant")
        self.assertIn("I scheduled that prompt task", shell.transcript[-2].body)
        self.assertEqual(shell.transcript[-1].kind, "assistant")
        self.assertIn("scheduled jobs", shell.transcript[-1].body)
        self.assertIn("Prompt · tell me a joke", shell.transcript[-1].body)

    def test_due_cron_tick_appends_prompt_result_to_open_shell(self) -> None:
        shell = self._make_shell()
        shell.runtime.create_cron_job(
            session_id=shell.session_id,
            name="Timed hello",
            schedule="2000-01-01T00:00:00+00:00",
            payload={"prompt": "say hello from cron"},
        )

        self.assertTrue(shell.runtime.has_due_cron_jobs(session_id=shell.session_id))

        with mock.patch.object(
            type(shell.runtime),
            "explain_next_step",
            return_value=SimpleNamespace(
                execution=SimpleNamespace(summary="hello from cron")
            ),
        ):
            shell._append_due_cron_jobs()

        self.assertEqual(shell.transcript[-1].kind, "assistant")
        self.assertEqual(shell.transcript[-1].body, "hello from cron")
        self.assertIn("cron", shell.transcript[-1].meta)
        self.assertFalse(shell.runtime.has_due_cron_jobs(session_id=shell.session_id))

    def test_prompt_cron_job_references_requested_skill_without_body_injection(
        self,
    ) -> None:
        shell = self._make_shell()
        skill = shell.runtime.inspect_skill("arxiv", session_id=shell.session_id)
        shell.runtime.create_cron_job(
            session_id=shell.session_id,
            name="Paper scan",
            schedule="2000-01-01T00:00:00+00:00",
            payload={
                "prompt": "find papers and write a markdown note",
                "skills": ["arxiv"],
            },
        )
        outcome = SimpleNamespace(execution=SimpleNamespace(summary="wrote paper note"))

        with (
            mock.patch.object(
                type(shell.runtime), "inspect_skill", return_value=skill
            ) as inspect_skill,
            mock.patch.object(
                type(shell.runtime),
                "explain_next_step",
                return_value=outcome,
            ) as explain,
        ):
            executions = shell.runtime.run_due_cron_jobs(session_id=shell.session_id)

        self.assertEqual(executions[0].summary, "wrote paper note")
        inspect_skill.assert_called_with("arxiv", session_id=shell.session_id)
        prompt = explain.call_args.kwargs["prompt"]
        self.assertIn(
            "This turn is running as a scheduled Elephant Agent cron job", prompt
        )
        self.assertIn("do not call tool.message.send", prompt)
        self.assertIn("Skill: ", prompt)
        self.assertIn("Full skill body: not injected automatically.", prompt)
        self.assertNotIn(skill.instruction_text.strip().splitlines()[0], prompt)

    def test_sub_agents_tool_runs_bounded_runtime_task(self) -> None:
        shell = self._make_shell()
        captured: dict[str, str] = {}
        child_tool_runtime = SimpleNamespace(
            subscribe=mock.Mock(return_value=mock.Mock())
        )
        child_runtime = SimpleNamespace(
            tool_runtime=child_tool_runtime,
            prepare_session_surface=mock.Mock(),
            explain_next_step=mock.Mock(),
        )

        def explain_next_step(*, session_id: str, prompt: str):
            captured["session_id"] = session_id
            captured["prompt"] = prompt
            return SimpleNamespace(
                execution=ExecutionResult(
                    execution_id="exec:child",
                    episode_id=session_id,
                    outcome="success",
                    summary="sub-agent result",
                )
            )

        child_runtime.explain_next_step.side_effect = explain_next_step

        with mock.patch(
            "apps.cli.runtime_cron_sub_agents._create_child_runtime",
            return_value=child_runtime,
        ) as create_child_runtime:
            result = shell.runtime.tool_runtime.invoke(
                "tool.sub_agents",
                {
                    "task": "inspect the cron implementation",
                    "name": "reviewer",
                    "skills": ["subagent-driven-development"],
                },
                session_id=shell.session_id,
                requester="model",
            )

        self.assertEqual(result.summary, "sub-agent result")
        create_child_runtime.assert_called_once_with(shell.runtime)
        child_session_id = captured["session_id"]
        self.assertNotEqual(child_session_id, shell.session_id)
        self.assertTrue(child_runtime.sub_agent_active)
        child_runtime.prepare_session_surface.assert_called_once_with(child_session_id)
        child_runtime.explain_next_step.assert_called_once()
        prompt = captured["prompt"]
        self.assertIn("bounded Elephant Agent sub-agent", prompt)
        self.assertIn("Do not call tool.sub_agents", prompt)
        self.assertIn("Sub-agent name: reviewer", prompt)

    def test_learning_sub_agent_uses_dedicated_system_prompt_without_generic_wrapper(
        self,
    ) -> None:
        shell = self._make_shell()
        captured: dict[str, object] = {}
        child_tool_runtime = SimpleNamespace(
            subscribe=mock.Mock(return_value=mock.Mock()), descriptor=SimpleNamespace()
        )
        child_runtime = SimpleNamespace(
            tool_runtime=child_tool_runtime,
            model_provider=SimpleNamespace(tool_runtime=child_tool_runtime),
            prepare_session_surface=mock.Mock(),
            close=mock.Mock(),
        )

        def run_turn(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                execution=ExecutionResult(
                    execution_id="exec:learning-child",
                    episode_id=str(kwargs["session_id"]),
                    outcome="success",
                    summary="learning result written",
                )
            )

        child_runtime._run_turn = mock.Mock(side_effect=run_turn)
        with mock.patch(
            "apps.cli.runtime_cron_sub_agents._create_child_runtime",
            return_value=child_runtime,
        ):
            result = shell.runtime.run_sub_agent(
                session_id=shell.session_id,
                task="Mode: manual\nLearning context packet: compact facts",
                name="Manual learning",
                allowed_tools=(
                    "tool.personal_model.search",
                    "tool.personal_model.update",
                ),
                system_prompt="[SYSTEM: Background Learning Agent]",
                learning_agent=True,
            )

        self.assertEqual(result["summary"], "learning result written")
        self.assertEqual(
            captured["prompt"], "Mode: manual\nLearning context packet: compact facts"
        )
        event_payload = captured["event_payload"]
        self.assertIsInstance(event_payload, dict)
        self.assertEqual(
            event_payload["system_prompt"], "[SYSTEM: Background Learning Agent]"
        )
        self.assertEqual(event_payload["context_mode"], "learning_agent")
        self.assertNotIn("bounded Elephant Agent sub-agent", str(captured["prompt"]))

    def test_sub_agents_start_returns_handle_and_emits_child_lifecycle_events(
        self,
    ) -> None:
        shell = self._make_shell()
        child_started = threading.Event()
        release_child = threading.Event()
        captured_events: list[ToolLifecycleEvent] = []

        def make_child_runtime(_runtime):
            child_tool_runtime = SimpleNamespace(
                subscribe=mock.Mock(return_value=mock.Mock())
            )
            child_runtime = SimpleNamespace(
                tool_runtime=child_tool_runtime,
                prepare_session_surface=mock.Mock(),
                close=mock.Mock(),
            )

            def explain_next_step(*, session_id: str, prompt: str):
                child_started.set()
                release_child.wait(timeout=5)
                return SimpleNamespace(
                    execution=ExecutionResult(
                        execution_id="exec:child-async",
                        episode_id=session_id,
                        outcome="success",
                        summary="async child result",
                    )
                )

            child_runtime.explain_next_step = mock.Mock(side_effect=explain_next_step)
            return child_runtime

        unsubscribe = shell.runtime.tool_runtime.subscribe(captured_events.append)
        try:
            with mock.patch(
                "apps.cli.runtime_cron_sub_agents._create_child_runtime",
                side_effect=make_child_runtime,
            ):
                started = shell.runtime.start_sub_agents(
                    session_id=shell.session_id,
                    tasks=(
                        {
                            "task": "inspect the async sub-agent implementation",
                            "name": "async-reviewer",
                            "skills": (),
                        },
                    ),
                    max_concurrency=1,
                )
                run_id = str(started["run_id"])

                self.assertEqual(started["status"], "running")
                self.assertTrue(child_started.wait(timeout=1))
                running = shell.runtime.inspect_sub_agent_run(
                    session_id=shell.session_id, run_id=run_id
                )
                self.assertEqual(running["status"], "running")

                release_child.set()
                joined = shell.runtime.inspect_sub_agent_run(
                    session_id=shell.session_id,
                    run_id=run_id,
                    wait_timeout_seconds=5,
                )
        finally:
            unsubscribe()

        self.assertEqual(joined["status"], "completed")
        self.assertIn("async child result", joined["summary"])
        child_events = [
            event
            for event in captured_events
            if event.invocation.tool_id == "tool.sub_agents"
            and event.invocation.arguments.get("sub_agent_child")
        ]
        self.assertTrue(
            any(event.phase == "execution.started" for event in child_events)
        )
        self.assertTrue(
            any(event.phase == "execution.completed" for event in child_events)
        )

    def test_sub_agent_child_writes_single_structured_result(self) -> None:
        from apps.cli import sub_agent_child

        previous_sub_agent_flag = os.environ.get("ELEPHANT_SUB_AGENT_CHILD")
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "prompt.txt"
            result_path = Path(tmpdir) / "result.json"
            prompt_path.write_text("delegated task", encoding="utf-8")
            execution = ExecutionResult(
                execution_id="exec:child",
                episode_id="session:child",
                outcome="completed",
                summary="child summary",
            )
            runtime = SimpleNamespace(
                prepare_session_surface=mock.Mock(),
                explain_next_step=mock.Mock(
                    return_value=SimpleNamespace(execution=execution)
                ),
            )

            with mock.patch(
                "apps.cli.sub_agent_child.CliRuntime.create", return_value=runtime
            ) as create:
                exit_code = sub_agent_child.main(
                    [
                        "--state-dir",
                        str(Path(tmpdir) / "state"),
                        "--session-id",
                        "session:child",
                        "--prompt-file",
                        str(prompt_path),
                        "--result-file",
                        str(result_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            create.assert_called_once()
            runtime.prepare_session_surface.assert_called_once_with("session:child")
            runtime.explain_next_step.assert_called_once_with(
                session_id="session:child", prompt="delegated task"
            )
            self.assertEqual(
                json.loads(result_path.read_text(encoding="utf-8")),
                {
                    "status": "completed",
                    "summary": "child summary",
                    "execution_id": "exec:child",
                    "session_id": "session:child",
                    "outcome": "completed",
                },
            )
            self.assertEqual(
                os.environ.get("ELEPHANT_SUB_AGENT_CHILD"), previous_sub_agent_flag
            )

    def test_tool_trace_emoji_covers_builtin_chat_tools(self) -> None:
        expected = {
            "tool.terminal.exec": "💻",
            "tool.process.manage": "🖥️",
            "tool.file.read": "📖",
            "tool.file.write": "✍️",
            "tool.file.patch": "🩹",
            "tool.file.search": "🔎",
            "tool.web.search": "🌐",
            "tool.web.read": "🌐",
            "tool.web.extract": "🌐",
            "tool.clarify": "❓",
            "tool.cron.manage": "⏰",
            "tool.personal_model.search": "🐘",
            "tool.personal_model.update": "🌱",
            "tool.personal_model.questions": "👂",
            "tool.code.execute": "🛠️",
            "tool.sub_agents": "🐘",
            "tool.skill.list": "🧩",
            "tool.skill.view": "🧩",
            "tool.skill.draft": "🧩",
            "tool.skill.manage": "🧩",
            "tool.message.send": "📨",
            "tool.todo.manage": "📋",
        }
        for tool_id, emoji in expected.items():
            self.assertEqual(shell_progress_trace._tool_trace_emoji(tool_id), emoji)
        self.assertEqual(
            shell_progress_trace._tool_trace_emoji("mcp.km.hot-articles"), "🧩"
        )

    def test_clarify_blocks_for_shell_input_and_returns_answer_as_tool_result(
        self,
    ) -> None:
        shell = self._make_shell()
        shell.runtime.set_clarify_surface(shell._interactive_clarify_surface())
        holder: dict[str, ExecutionResult] = {}

        def invoke_clarify() -> None:
            holder["result"] = shell.runtime.tool_runtime.invoke(
                "tool.clarify",
                {"question": "Which target?", "choices": ["alpha", "beta"]},
                session_id=shell.session_id,
            )

        thread = threading.Thread(target=invoke_clarify)
        thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if shell._clarify_state is not None:
                break
            time.sleep(0.01)
        self.assertIsNotNone(shell._clarify_state)

        self.assertTrue(route_clarify_answer(shell, "2"))
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        result = holder["result"]
        self.assertEqual(result.outcome, "success")
        self.assertIn("question: Which target?", result.summary)
        self.assertIn("user_response: beta", result.summary)
        self.assertIsNone(shell._clarify_state)

    def test_clarify_render_adds_title_emoji_and_hint_spacing(self) -> None:
        shell = self._make_shell()

        with shell._clarify_lock:
            shell._clarify_state = ShellClarifyState(
                question="Which target?",
                mode="choice",
                choices=("alpha", "beta"),
                response_queue=Queue(maxsize=1),
            )
        choice_plain = "".join(text for _style, text in render_clarify_fragments(shell))

        self.assertIn("Clarification needed 🤔", choice_plain)
        self.assertIn(
            "Type a number or a custom answer, then press Enter.\n", choice_plain
        )
        self.assertTrue(choice_plain.endswith("Enter.\n"))

        with shell._clarify_lock:
            shell._clarify_state = ShellClarifyState(
                question="What should I do?",
                mode="open",
                choices=(),
                response_queue=Queue(maxsize=1),
            )
        open_plain = "".join(text for _style, text in render_clarify_fragments(shell))

        self.assertIn("Type your answer, then press Enter.\n", open_plain)
        self.assertTrue(open_plain.endswith("Enter.\n"))

    def test_assistant_render_strips_markdown_markers_from_plain_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            profile_dir = root / "profile"
            profile_dir.mkdir()
            (root / "profile.json").write_text(
                json.dumps(
                    {
                        "profile_id": "profile-companion",
                        "display_name": "Elephant Agent",
                        "mode": "companion",
                    }
                ),
                encoding="utf-8",
            )

            runtime = CliRuntime.create(state_dir=state_dir)
            runtime.update_identity_state(
                profile_id="profile-companion",
                elephant_identity_text="Stay durable.",
            )
            session = runtime.create_elephant(elephant_id="atlas")
            shell = ProductizedShell(
                runtime, session_id=session.session_id, opened="Shaped new"
            )
            rendered = shell._render_entry(
                TranscriptEntry(
                    kind="assistant",
                    title="Elephant Agent",
                    body="You're the **Local Operator** in this session.",
                )
            )
            plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
            self.assertIn("Local Operator", plain)
            self.assertNotIn("**", plain)

    def test_assistant_reasoning_heading_renders_without_leading_bullet(self) -> None:
        shell = self._make_shell()
        rendered = shell._render_entry(
            TranscriptEntry(
                kind="assistant",
                title="Elephant Agent",
                body="<think>Inspect memory state first.</think>The memory summary is ready.",
            )
        )

        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        first_line = next((line for line in plain.splitlines() if line.strip()), "")

        self.assertEqual(first_line.strip(), "🐾 Elephant Agent's Trail:")
        self.assertNotIn("● 🐾 Elephant Agent's Trail:", plain)

    def test_next_command_prefers_queued_followup_before_prompting(self) -> None:
        shell = self._make_shell()
        shell._pending_commands.append(PendingShellCommand(command="queued followup"))

        with mock.patch.object(
            shell, "_read_command", side_effect=AssertionError("should not prompt")
        ):
            queued = shell._next_command()

        self.assertEqual(queued, PendingShellCommand(command="queued followup"))

    def test_enqueue_followup_command_does_not_preappend_transcript_entry(self) -> None:
        shell = self._make_shell()
        original_len = len(shell.transcript)

        shell._enqueue_followup_command("queued followup")

        self.assertEqual(len(shell.transcript), original_len)
        queued = shell._next_command()
        self.assertEqual(queued, PendingShellCommand(command="queued followup"))

    def test_queued_followup_enters_transcript_only_when_dispatched(self) -> None:
        shell = self._make_shell()
        shell._enqueue_followup_command("queued followup")

        with mock.patch.object(
            shell, "_handle_conversational_surface_request", return_value=True
        ):
            shell._dispatch(shell._next_command().command)

        queued_entries = [
            entry
            for entry in shell.transcript
            if entry.kind == "user" and entry.body == "queued followup"
        ]
        self.assertEqual(len(queued_entries), 1)

    def test_queued_followup_fragments_stack_without_blank_lines(self) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(48)
        shell._enqueue_followup_command("who are you")
        shell._enqueue_followup_command("how are you")
        shell._enqueue_followup_command("hi")

        fragments = shell._render_queued_followup_fragments()
        lines = "".join(text for _style, text in fragments).splitlines()

        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0].strip(), "› who are you")
        self.assertEqual(lines[1].strip(), "› how are you")
        self.assertEqual(lines[2].strip(), "› hi")

    def test_queue_preview_rows_are_narrower_than_sent_user_rows(self) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(48)
        shell._enqueue_followup_command("queued followup")

        preview_lines = "".join(
            text for _style, text in shell._render_queued_followup_fragments()
        ).splitlines()
        sent = shell._render_entry(
            TranscriptEntry(
                kind="user",
                title="You",
                body="queued followup",
            )
        )
        sent_lines = (sent.plain if hasattr(sent, "plain") else str(sent)).splitlines()

        self.assertEqual(
            _display_width(preview_lines[0]),
            shell._history_row_width() - QUEUE_PREVIEW_INSET,
        )
        self.assertEqual(_display_width(sent_lines[0]), shell._history_row_width())

    def test_turn_progress_fragments_show_queued_followup_count(self) -> None:
        shell = self._make_shell()

        fragments = shell._render_turn_progress_fragments(
            prompt="draft the next release note",
            tick=0,
            queued_count=2,
        )

        rendered = "".join(text for _style, text in fragments)
        self.assertIn("Elephant Agent is orienting", rendered)
        self.assertIn("queued scrolls · 2 messages", rendered)

    def test_turn_progress_fragments_drop_queue_scroll_hint_but_keep_spacing(
        self,
    ) -> None:
        shell = self._make_shell()

        fragments = shell._render_turn_progress_fragments(
            prompt="draft the next release note",
            tick=0,
        )

        rendered = "".join(text for _style, text in fragments)
        self.assertNotIn("Press Enter to queue another scroll.", rendered)
        self.assertTrue(rendered.endswith("\n"))

    def test_turn_progress_fragments_keep_live_tool_lines_on_separate_rows(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._rendered_entries = len(shell.transcript)
        shell._append_tooltrace_line("┊ 📚 Calling skill…")
        shell._append_tooltrace_line("┊ 📚 skill        apple-notes  0.3s")

        fragments = shell._render_turn_progress_fragments(
            prompt="open notes",
            tick=0,
        )

        rendered = "".join(text for _style, text in fragments)
        self.assertIn("\n┊ 📚 Calling skill…", rendered)
        self.assertIn("\n┊ 📚 skill        apple-notes  0.3s", rendered)
        self.assertNotIn("skill…┊ 📚 skill", rendered)

    def test_turn_progress_fragments_surface_state_focus_resolution_summary(
        self,
    ) -> None:
        shell = self._make_shell()

        fragments = shell._render_turn_progress_fragments(
            prompt="draft the next release note",
            tick=0,
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "relationship",
                        "detail": "continuity_notes=1",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    }
                },
                {
                    "payload": {
                        "stage": "state_focus",
                        "detail": (
                            "state_focus=exploration confidence=0.82 focus=work-release "
                            "scope=elephant degradation=none weak_assist=false "
                            "weak_outcome=not-requested fallback=none candidates=3"
                        ),
                        "recorded_at": "2026-04-17T08:00:00.035000+00:00",
                    }
                },
            ),
        )

        rendered = "".join(text for _style, text in fragments)
        self.assertIn(
            "┊ 🐘 model           exploration · 35ms · elephant · conf 0.82", rendered
        )

    def test_turn_progress_fragments_omit_context_and_request_progress_rows(
        self,
    ) -> None:
        shell = self._make_shell()

        fragments = shell._render_turn_progress_fragments(
            prompt="draft the next release note",
            tick=0,
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
            ),
        )

        rendered = "".join(text for _style, text in fragments)

        self.assertNotIn("┊ 🧩 context", rendered)
        self.assertNotIn("┊ 📈 request", rendered)
        self.assertNotIn("provider running", rendered)

    def test_record_kernel_event_trace_appends_skill_disclosure_line(self) -> None:
        shell = self._make_shell()

        shell._record_kernel_event_trace(
            {
                "event_type": "skill.disclosed",
                "payload": {
                    "skill_id": "skill.research.web",
                    "display_name": "Web research skill",
                    "disclosure_kind": "state-focus.overlay",
                },
            }
        )

        tool_entries = [
            entry for entry in shell.transcript if entry.kind == "tooltrace"
        ]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn(
            "┊ 📚 disclosed    Web research skill (skill.research.web) · state-focus.overlay",
            tool_entries[0].body,
        )

    def test_record_kernel_event_trace_omits_recall_tooltrace_rows(self) -> None:
        shell = self._make_shell()

        shell._record_kernel_event_trace(
            {
                "event_type": "kernel.stage",
                "payload": {
                    "stage": "recall",
                    "detail": "status=miss count=0 bytes=0",
                    "recorded_at": "2026-04-17T08:00:00+00:00",
                },
            }
        )

        self.assertFalse(
            [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        )

    def test_record_kernel_event_trace_updates_context_projection_after_compaction(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 1800

        shell._record_kernel_event_trace(
            {
                "event_type": "kernel.stage",
                "payload": {
                    "stage": "context-compact",
                    "detail": (
                        "reason=preflight tokens=1800->620 messages=80->12 "
                        "compacted_messages=68 tail=10 semantic_cached=2 semantic_pending=5 semantic_missed=1"
                    ),
                    "recorded_at": "2026-04-17T08:00:00+00:00",
                },
            }
        )

        self.assertEqual(shell._last_prompt_tokens, 620)
        tool_entries = [
            entry for entry in shell.transcript if entry.kind == "tooltrace"
        ]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn(
            "┊ 🧩 context      projection compact · est 1800->620 tokens · preflight",
            tool_entries[0].body,
        )
        self.assertIn(
            "projection compact · est 1800->620 tokens · preflight",
            tool_entries[0].body,
        )

    def test_record_kernel_event_trace_uses_provider_prompt_usage_for_status_bar(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 1800

        shell._record_kernel_event_trace(
            {
                "event_type": "kernel.stage",
                "payload": {
                    "stage": "context-usage",
                    "detail": "prompt_tokens=720 completion_tokens=40 total_tokens=760",
                    "recorded_at": "2026-04-17T08:00:00+00:00",
                },
            }
        )

        self.assertEqual(shell._last_prompt_tokens, 1800)
        self.assertEqual(shell._last_provider_prompt_tokens, 720)
        self.assertFalse(
            [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        )

    def test_record_kernel_event_trace_tracks_latest_context_projection_status(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 1800

        for prompt_tokens in (2400, 720):
            shell._record_kernel_event_trace(
                {
                    "event_type": "kernel.stage",
                    "payload": {
                        "stage": "context-projection",
                        "detail": f"prompt_tokens={prompt_tokens} token_budget=4096 source=generation",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    },
                }
            )

        self.assertEqual(shell._last_prompt_tokens, 720)
        self.assertEqual(shell._last_provider_prompt_tokens, 0)
        self.assertFalse(
            [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        )


if __name__ == "__main__":
    unittest.main()
