from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.cli.shell import (
    BRAND_ACCENT_STRONG,
    BRAND_MUTED,
    Console,
    GROWTH_PROGRESS_EMPTY,
    GROWTH_PROGRESS_FILLED,
    GROWTH_PROGRESS_WIDTH,
    RICH_AVAILABLE,
    TranscriptEntry,
)
from apps.cli.shell_composer import prompt_style_map
from apps.cli.shell_render import _render_tooltrace_body_line
import apps.cli.shell_render as shell_render
from apps.cli.shell_banner import (
    _learning_job_execution_summary,
    _skill_affinity_summary,
)
import apps.cli.shell_progress_trace as shell_progress_trace
from apps.cli.shell_ui import (
    LIVE_DIFF_ADD_FG,
    LIVE_DIFF_FILE_FG,
    LIVE_DIFF_HUNK_FG,
    LIVE_DIFF_REMOVE_FG,
    SETTLED_DIFF_ADD_FG,
    SETTLED_DIFF_FILE_FG,
    SETTLED_DIFF_HUNK_FG,
    SETTLED_DIFF_REMOVE_FG,
)
from packages.contracts import (
    ContextBundle,
    EventEnvelope,
    ExecutionResult,
    Fact,
    OpenQuestion,
    PromptEnvelope,
)
from packages.growth import GrowthTurnSignals, apply_turn_growth, default_growth_state
from tests.unit.cli.shell_test_support import ShellTestBase


class ShellStatusBannerTest(ShellTestBase):
    def test_shell_frame_banner_uses_personal_model_readiness_sections(self) -> None:
        shell = self._make_shell()
        frame = shell._render_shell_frame()
        if RICH_AVAILABLE:
            console = Console(width=120, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(getattr(frame, "renderable", ""))
        self.assertIn("Ready for this chat", rendered)
        self.assertIn("What I know", rendered)
        self.assertIn("Skills for you", rendered)
        self.assertNotIn("What matters now", rendered)
        self.assertNotIn("This Episode", rendered)
        self.assertNotIn("Start with the person", rendered)
        self.assertNotIn("What Elephant Agent is carrying forward", rendered)
        self.assertNotIn("Recent activity", rendered)
        self.assertNotIn("Support style", rendered)
        self.assertNotIn("Next best context", rendered)
        self.assertNotIn("grounding ·", rendered)

    def test_shell_frame_banner_summarizes_pm_lenses_and_curiosity(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        now = datetime.now(timezone.utc)
        shell.runtime.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact:identity:style",
                personal_model_id=session.personal_model_id,
                lens="identity",
                text="Prefers direct technical review.",
                confidence=0.9,
                committed_at=now,
                source="user_explicit",
                metadata={"topic": "identity.style.review"},
            )
        )
        shell.runtime.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact:world:project",
                personal_model_id=session.personal_model_id,
                lens="world",
                text="Currently building durable agent systems.",
                confidence=0.9,
                committed_at=now,
                source="user_explicit",
                metadata={"topic": "world.projects.aegis"},
            )
        )
        shell.runtime.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact:world:skill:diagram",
                personal_model_id=session.personal_model_id,
                lens="world",
                text="Architecture diagrams are useful for this user.",
                confidence=0.9,
                committed_at=now,
                source="user_explicit",
                metadata={
                    "topic": "world.skills.affinity.architecture_diagram",
                    "skill_id": "architecture-diagram",
                    "projection_policy": "skill_shelf_candidate",
                },
            )
        )
        shell.runtime.repository.upsert_open_question(
            OpenQuestion(
                question_id="question:pulse:focus",
                personal_model_id=session.personal_model_id,
                lens="pulse",
                sub_lens="current_focus",
                text="What should I treat as the current highest-priority thread?",
                rationale="Current focus would improve future help.",
                priority=0.8,
                sensitivity="low",
                source="contextual",
                created_at=now,
            )
        )
        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        context_frame = shell.runtime.inspect_context_frame(session.episode_id)
        provider = dict(shell.runtime.provider_summary())
        growth = shell.runtime.inspect_growth(session_id=shell.session_id)

        rendered = shell._render_status_column(
            session, continuity, context_frame, provider, growth
        )
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)

        self.assertIn("🐘 What I know", plain)
        self.assertIn("saved · identity 1 · world 2 · 2 lens empty", plain)
        self.assertIn(
            "question (pulse · current_focus) · What should I treat as the current highest-priority thread?",
            plain,
        )
        self.assertIn("🧩 Skills for you", plain)
        self.assertIn("affinities · 1 learned · 1 active", plain)
        self.assertNotIn("affinities · Architecture Diagram", plain)
        self.assertIn("active ·", plain)
        self.assertIn("built-in", plain)
        self.assertIn("discover ·", plain)
        self.assertNotIn("Building durable agent systems.", plain)
        self.assertNotIn("proof-backed", plain)

    def test_skill_affinities_report_metrics_without_skill_names(self) -> None:
        now = datetime.now(timezone.utc)
        summary = _skill_affinity_summary(
            facts=(
                Fact(
                    fact_id="fact:world:skill:workflow",
                    personal_model_id="you",
                    lens="world",
                    text="Workflow automation fits the user's repeated work.",
                    confidence=0.83,
                    committed_at=now,
                    source="user_explicit",
                    metadata={
                        "topic": "world.skills.affinity.workflow_automation",
                        "skill_id": "workflow-automation",
                        "projection_policy": "skill_shelf_candidate",
                    },
                ),
            ),
        )

        self.assertEqual(summary, "1 learned · 1 active")

    def test_skill_affinities_follow_dashboard_topic_detection_without_projection_filter(
        self,
    ) -> None:
        now = datetime.now(timezone.utc)
        summary = _skill_affinity_summary(
            facts=(
                Fact(
                    fact_id="fact:world:skill:paper",
                    personal_model_id="you",
                    lens="world",
                    text="Paper workflow skills match the user's research process.",
                    confidence=0.8,
                    committed_at=now,
                    source="user_explicit",
                    metadata={
                        "topic": "world.skills.affinity.paper_workflow",
                        "skill_id": "paper-workflow",
                        "projection_policy": "dashboard-only",
                    },
                ),
            ),
        )

        self.assertEqual(summary, "1 learned · 1 active")

    def test_learning_job_execution_summary_counts_executed_jobs(self) -> None:
        runtime = SimpleNamespace(
            repository=SimpleNamespace(
                list_learning_jobs=lambda personal_model_id: (
                    SimpleNamespace(status="queued", started_at=None, finished_at=None),
                    SimpleNamespace(
                        status="completed", started_at=object(), finished_at=object()
                    ),
                    SimpleNamespace(
                        status="failed", started_at=object(), finished_at=object()
                    ),
                )
            )
        )

        self.assertEqual(
            _learning_job_execution_summary(runtime, "you"),
            "2 run(s) · 1 completed · 1 failed",
        )

    def test_shell_frame_surfaces_user_facing_context_summary(self) -> None:
        shell = self._make_shell()
        frame = shell._render_shell_frame()
        if RICH_AVAILABLE:
            console = Console(width=120, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(getattr(frame, "renderable", ""))

        self.assertIn("Ready for this chat", rendered)
        self.assertIn("What I know", rendered)
        self.assertIn("Skills for you", rendered)
        self.assertIn("saved · No saved user notes yet.", rendered)
        self.assertNotIn("grounding ·", rendered)
        self.assertNotIn("proof-backed", rendered)
        self.assertNotIn("This Episode", rendered)
        self.assertNotIn("focus right now ·", rendered)
        self.assertNotIn("why this context ·", rendered)
        self.assertNotIn("What this wake will carry in", rendered)
        self.assertNotIn("SessionFrame", rendered)
        self.assertNotIn("assistant_display_name:", rendered)
        self.assertNotIn("opening_profile_gap:", rendered)
        self.assertNotIn("current_work_summary:", rendered)

    def test_shell_frame_filters_opening_prompt_like_state_text(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        state = shell.runtime.ensure_elephant_state(session)
        shell.runtime.repository.upsert_state(
            replace(
                state,
                summary="Open the wake surface proactively before the user sends a new message. assistant_display_name: Miles current_work_summary: Ship the release.",
            )
        )

        frame = shell._render_shell_frame()
        if RICH_AVAILABLE:
            console = Console(width=120, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(getattr(frame, "renderable", ""))

        self.assertIn("now · Ready to pick the thread back up when you are.", rendered)
        self.assertNotIn("assistant_display_name:", rendered)
        self.assertNotIn(
            "Open the wake surface proactively before the user sends a new message.",
            rendered,
        )

    def test_status_column_renders_carrying_forward_with_bold_label_and_markdown_value(
        self,
    ) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        context_frame = shell.runtime.inspect_context_frame(session.episode_id)
        provider = dict(shell.runtime.provider_summary())
        growth = shell.runtime.inspect_growth(session_id=shell.session_id)
        state = shell.runtime.ensure_elephant_state(session)
        shell.runtime.repository.upsert_state(
            replace(
                state,
                current_context_note="**Ship the release**",
                summary="",
            )
        )

        rendered = shell._render_status_column(
            session, continuity, context_frame, provider, growth
        )
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)

        self.assertIn("✨ Ready for this chat", plain)
        self.assertIn("now · Ship the release", plain)
        self.assertNotIn("next step ·", plain)
        self.assertNotIn("**", plain)
        if RICH_AVAILABLE:
            styles = {str(span.style) for span in rendered.spans}
            self.assertIn(f"bold {shell_render.BRAND_ACCENT}", styles)
            self.assertIn(f"bold {shell_render.BRAND_LIGHT}", styles)

    def test_status_column_compacts_long_markdown_state_into_summary(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        context_frame = shell.runtime.inspect_context_frame(session.episode_id)
        provider = dict(shell.runtime.provider_summary())
        growth = shell.runtime.inspect_growth(session_id=shell.session_id)
        state = shell.runtime.ensure_elephant_state(session)
        shell.runtime.repository.upsert_state(
            replace(
                state,
                summary=(
                    "当然可以。下面是我目前对你的了解。\n\n"
                    "# 已知信息\n"
                    "| 字段 | 内容 |\n"
                    "| --- | --- |\n"
                    "| name | Xunzhuo |\n"
                    "| city | Chengdu |\n"
                    "后面这整段历史内容不应该原样出现在 banner 里。"
                ),
                current_context_note="整理成更短的摘要\n并保留必要信息",
            )
        )

        rendered = shell._render_status_column(
            session, continuity, context_frame, provider, growth
        )
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)

        self.assertIn("now · 整理成更短的摘要 · 并保留必要信息", plain)
        self.assertNotIn("next step ·", plain)
        self.assertNotIn("# 已知信息", plain)
        self.assertNotIn("| 字段 | 内容 |", plain)
        self.assertNotIn("后面这整段历史内容不应该原样出现在 banner 里。", plain)

    def test_shell_frame_surfaces_frozen_session_focus_and_counts(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        profile = shell.runtime._load_profile(session.personal_model_id)
        shell.runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:first",
                episode_id=session.session_id,
                outcome="ok",
                summary="first reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:first",
                event_type="turn.received",
                episode_id=session.session_id,
                source="cli",
                payload={"message": "first ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:first",
                episode_id=session.session_id,
                prompt_envelope=PromptEnvelope(
                    frozen_prefix="FIRST PREFIX",
                    session_snapshot="FIRST SNAPSHOT",
                    loop_context="FIRST INJECTIONS",
                ),
            ),
        )

        frame = shell._render_shell_frame()
        if RICH_AVAILABLE:
            console = Console(width=120, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(getattr(frame, "renderable", ""))

        self.assertIn("saved · No saved user notes yet.", rendered)
        self.assertNotIn("No durable elephant focus is available yet.", rendered)
        self.assertNotIn("grounding ·", rendered)
        self.assertNotIn("proof-backed", rendered)
        self.assertNotIn("focus right now ·", rendered)
        self.assertNotIn("why this context ·", rendered)

    def test_frozen_slash_command_surfaces_only_initial_frozen_sections(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        profile = shell.runtime._load_profile(session.personal_model_id)
        shell.runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:first",
                episode_id=session.session_id,
                outcome="ok",
                summary="first reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:first",
                event_type="turn.received",
                episode_id=session.session_id,
                source="cli",
                payload={"message": "first ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:first",
                episode_id=session.session_id,
                prompt_envelope=PromptEnvelope(
                    frozen_prefix="FIRST PREFIX",
                    session_snapshot="FIRST SNAPSHOT",
                    loop_context="FIRST INJECTIONS",
                ),
            ),
        )
        shell.runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:second",
                episode_id=session.session_id,
                outcome="ok",
                summary="second reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:second",
                event_type="turn.received",
                episode_id=session.session_id,
                source="cli",
                payload={"message": "second ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:second",
                episode_id=session.session_id,
                prompt_envelope=PromptEnvelope(
                    frozen_prefix="SECOND PREFIX",
                    session_snapshot="SECOND SNAPSHOT",
                    loop_context="SECOND INJECTIONS",
                ),
            ),
        )

        handled = shell._handle_slash_command("/frozen")

        self.assertFalse(handled)
        self.assertEqual(shell.transcript[-1].title, "Unknown command")
        self.assertIn("/frozen", shell.transcript[-1].body)
        self.assertNotIn(
            "system prompt (tool fallback) :: tool_schema", shell.transcript[-1].body
        )
        self.assertNotIn("FIRST TOOLS", shell.transcript[-1].body)
        self.assertIn("help: /help", shell.transcript[-1].body)
        self.assertNotIn("frozen_skill_index:", shell.transcript[-1].body)
        self.assertNotIn("SECOND PREFIX", shell.transcript[-1].body)
        self.assertNotIn("user: first ask", shell.transcript[-1].body)

    def test_settled_state_focus_meta_stays_muted_in_transcript(self) -> None:
        shell = self._make_shell()
        rendered = shell._render_entry(
            TranscriptEntry(
                kind="assistant",
                title="Elephant Agent",
                body="reply",
                meta="routing · resume · 56ms · lineage · 0.94",
            )
        )

        self.assertIn(
            "routing · resume · 56ms · lineage · 0.94",
            rendered.plain if hasattr(rendered, "plain") else str(rendered),
        )

    def test_live_state_focus_progress_uses_steady_orange_trace_style(self) -> None:
        text = shell_progress_trace.render_tool_trace_text(
            "┊ 🧭 routing      resume · 56ms · lineage · 0.94"
        )

        self.assertEqual(text.spans[0].style, shell_render.BRAND_ACCENT_STRONG)

    def test_growth_panel_reports_enabled_and_self_learned_skill_counts_without_internal_next_move(
        self,
    ) -> None:
        shell = self._make_shell()
        shell.runtime.create_experience_skill(
            skill_id="self-learned-shell-fix",
            display_name="Self Learned Shell Fix",
            summary="Recover shell work after a failed command.",
            instruction_text="Inspect stderr, retry carefully, and summarize the durable fix.",
            session_id=shell.session_id,
        )

        session = shell.runtime.inspect_session(shell.session_id)
        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        provider = dict(shell.runtime.provider_summary())
        lines = shell._recent_activity_lines(session, continuity, provider)
        enabled_skills = tuple(
            skill
            for skill in shell.runtime.skill_catalog(session_id=shell.session_id)
            if skill.enabled
        )

        self.assertIn(f"skills · {len(enabled_skills)} enabled · 1 self-learned", lines)
        self.assertFalse(any(line.startswith("next move ·") for line in lines))
        self.assertFalse(any(line.startswith("focus ·") for line in lines))
        self.assertFalse(any(line.startswith("grounding ·") for line in lines))

    def test_growth_progress_bar_uses_glyph_bar_and_orange_fill(self) -> None:
        shell = self._make_shell()
        growth = type(
            "GrowthProbe", (), {"progress_ratio": 0.40, "progress_percent": 40}
        )()

        bar = shell._growth_progress_bar(growth)
        self.assertEqual(
            bar,
            (GROWTH_PROGRESS_FILLED * 6)
            + (GROWTH_PROGRESS_EMPTY * (GROWTH_PROGRESS_WIDTH - 6)),
        )

        styled = shell._styled_growth_progress_bar(growth)
        self.assertEqual(styled.plain, bar)
        if RICH_AVAILABLE:
            styles = [span.style for span in styled.spans]
            self.assertIn(BRAND_ACCENT_STRONG, styles)
            self.assertIn(BRAND_MUTED, styles)

    def test_diff_styles_use_brighter_live_palette_and_dimmer_settled_palette(
        self,
    ) -> None:
        style_map = prompt_style_map()

        self.assertEqual(
            style_map["progress-output-file"], f"fg:{LIVE_DIFF_FILE_FG} bold"
        )
        self.assertEqual(
            style_map["progress-output-hunk"], f"fg:{LIVE_DIFF_HUNK_FG} bold"
        )
        self.assertEqual(
            style_map["progress-output-add"], f"fg:{LIVE_DIFF_ADD_FG} bold"
        )
        self.assertEqual(
            style_map["progress-output-remove"], f"fg:{LIVE_DIFF_REMOVE_FG} bold"
        )
        self.assertEqual(
            _render_tooltrace_body_line("a/notes.md → b/notes.md").style,
            SETTLED_DIFF_FILE_FG,
        )
        self.assertEqual(
            _render_tooltrace_body_line("@@ -1 +1 @@").style, SETTLED_DIFF_HUNK_FG
        )
        self.assertEqual(
            _render_tooltrace_body_line("+added").style, SETTLED_DIFF_ADD_FG
        )
        self.assertEqual(
            _render_tooltrace_body_line("-removed").style, SETTLED_DIFF_REMOVE_FG
        )

    def test_status_bar_fragments_include_checkpoint_and_growth_progress(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        update = apply_turn_growth(
            default_growth_state(session.personal_model_id),
            GrowthTurnSignals(
                session_id=shell.session_id,
                profile_id=session.personal_model_id,
                total_tokens=320,
            ),
        )
        shell.runtime.repository.upsert_personal_model_growth(update.after.state)
        shell._last_prompt_tokens = 12_800
        shell._last_turn_elapsed_seconds = 12

        fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("12s", rendered)
        self.assertIn("Evidence I", rendered)
        self.assertIn(shell._build_context_bar(update.after.progress_percent), rendered)
        self.assertIn(
            f"checkpoint {update.after.level} · {update.after.progress_percent}%",
            rendered,
        )

        styles = {style for style, _text in fragments if style}
        self.assertIn("class:status-bar-level", styles)
        self.assertIn("class:status-bar-growth-bracket", styles)
        self.assertIn("class:status-bar-growth-fill", styles)
        self.assertIn("class:status-bar-growth-empty", styles)

    def test_status_bar_stream_phase_reads_as_following_with_path_dots(self) -> None:
        shell = self._make_shell()
        shell._streaming_response_active = True

        fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("following", rendered)
        self.assertNotIn("replying", rendered)
        self.assertTrue(
            any(
                frame in rendered
                for frame in ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
            )
        )
        self.assertFalse(any(frame in rendered for frame in ("▁", "▃", "▅", "▇")))

    def test_status_bar_think_phase_reads_as_orienting_with_reply_pulse(self) -> None:
        shell = self._make_shell()
        shell._turn_started_at = time.monotonic()

        fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("orienting", rendered)
        self.assertNotIn("thinking", rendered)
        self.assertTrue(any(frame in rendered for frame in ("▁", "▃", "▅", "▇")))

    def test_status_bar_fragments_keep_previous_usage_during_live_turn(self) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 12_800
        shell._last_provider_prompt_tokens = 6_400
        shell._turn_started_at = time.monotonic()

        with mock.patch.object(
            type(shell.runtime),
            "provider_summary",
            return_value={"model_id": "gpt-5.4", "context_window_tokens": 128_000},
        ):
            fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("6K/128K", rendered)
        self.assertIn("5%", rendered)
        self.assertNotIn("--/128K", rendered)
        self.assertNotIn("10%", rendered)

    def test_status_bar_fragments_show_committed_provider_usage_after_turn(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 14_000
        shell._last_provider_prompt_tokens = 43_500

        with mock.patch.object(
            type(shell.runtime),
            "provider_summary",
            return_value={"model_id": "glm5", "context_window_tokens": 128_000},
        ):
            fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("44K/128K", rendered)
        self.assertIn("34%", rendered)
        self.assertIn("◔", rendered)
        self.assertNotIn("req ", rendered)

    def test_status_bar_fragments_use_lightweight_growth_projection(self) -> None:
        shell = self._make_shell()

        with mock.patch.object(
            type(shell.runtime),
            "inspect_growth",
            side_effect=AssertionError("status bar should avoid heavy inspect_growth"),
        ):
            fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("Evidence I", rendered)
        self.assertIn("checkpoint", rendered)


if __name__ == "__main__":
    unittest.main()
