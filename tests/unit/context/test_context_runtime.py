from __future__ import annotations

from dataclasses import is_dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.context import (
    CONTEXT_SURFACES,
    ContextBudgetRequest,
    ContextRuntime,
    ContextSourceTrace,
    DeterministicBudgetManager,
    DeterministicRetrievalScheduler,
    DeterministicSummaryHook,
    LayeredContextPlanner,
    MarkdownPromptRenderer,
)
from packages.contracts import (
    RecallEvidence,
)
from packages.contracts.layers import Episode
from packages.contracts.runtime import StateFocusDecision


class ContextRuntimeTest(unittest.TestCase):
    def _session(
        self,
        *,
        interruption_state: str | None = None,
        parent_session_id: str | None = None,
    ) -> Episode:
        return Episode(
            episode_id="session-1",
            state_id="state:test",
            personal_model_id="profile-companion",
            entry_surface="test",
            elephant_id="elephant-a",
            status="open",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            parent_episode_id=parent_session_id,
            interruption_state=interruption_state,
        )

    def _work_items(self) -> tuple[SimpleNamespace, ...]:
        return (
            SimpleNamespace(
                work_item_id="work-1",
                session_id="session-1",
                title="Ship the context layer",
                status="active",
                priority="high",
                dependencies=("work-0",),
                evidence_refs=("artifact-1",),
            ),
        )

    def _state_focus(
        self,
        *,
        focus_family: str = "resume",
        focus_work_item_ids: tuple[str, ...] = ("work-1",),
        continuity_signal: str = "resume",
        focus_scope: str = "lineage",
        context_budget: str = "narrow",
    ) -> StateFocusDecision:
        return StateFocusDecision(
            focus_family=focus_family,
            confidence=0.92,
            focus_work_item_ids=focus_work_item_ids,
            continuity_signal=continuity_signal,
            focus_scope=focus_scope,
            context_budget=context_budget,
        )

    def _memories(self) -> tuple[RecallEvidence, ...]:
        return (
            RecallEvidence(
                evidence_id="evidence-1",
                episode_id="session-1",
                kind="decision",
                content="Prefer explicit budget allocation over blind truncation.",
                work_item_ids=("work-1",),
                tags=("budget", "continuity"),
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            RecallEvidence(
                evidence_id="evidence-2",
                episode_id="session-1",
                kind="summary",
                content="The last turn asked for recovery after a gap.",
                work_item_ids=("work-1",),
                tags=("recovery",),
                created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
            RecallEvidence(
                evidence_id="evidence-3",
                episode_id="session-1",
                kind="note",
                content="This evidence is mostly filler to trigger overflow.",
                work_item_ids=(),
                tags=("filler",),
                created_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
            ),
        )

    def test_context_inventory_is_stable(self) -> None:
        self.assertEqual(
            CONTEXT_SURFACES,
            (
                "ContextLayerBudget",
                "ContextBudgetRequest",
                "ContextBudgetPlan",
                "ContextSummaryRequest",
                "ContextRetrievalRequest",
                "ContextLayerSnapshot",
                "EpisodeFrozenContext",
                "StateSnapshot",
                "EpisodeReplay",
                "LoopContext",
                "RequestAttachments",
                "EpisodeFrame",
                "ContextSourceTrace",
                "ContextAssemblyPlan",
                "ContextAssemblyResult",
                "SummaryHook",
                "RetrievalScheduler",
                "BudgetManager",
                "PromptRenderer",
                "ContextPlanner",
                "DeterministicBudgetManager",
                "DeterministicRetrievalScheduler",
                "DeterministicSummaryHook",
                "MarkdownPromptRenderer",
                "EpisodeFrameBuilder",
                "LayeredContextPlanner",
                "ContextRuntime",
            ),
        )

    def test_public_shapes_are_dataclasses_or_protocol_exports(self) -> None:
        runtime = ContextRuntime(instruction_refs=("system:keep stable",), total_tokens=160)
        self.assertTrue(hasattr(runtime, "descriptor"))
        self.assertEqual(runtime.descriptor.capability_id, "context.runtime")
        for contract_type in (
            ContextBudgetRequest,
            ContextSourceTrace,
        ):
            self.assertTrue(is_dataclass(contract_type), contract_type.__name__)

    def test_budget_manager_allocates_and_reports_overflow(self) -> None:
        manager = DeterministicBudgetManager()
        plan = manager.allocate(
            120,
            (
                ContextBudgetRequest("stable_prefix", 32, minimum_tokens=16, required=True, priority=100),
                ContextBudgetRequest(
                    "session_snapshot",
                    72,
                    minimum_tokens=32,
                    required=True,
                    priority=90,
                ),
                ContextBudgetRequest("loop_context", 32, minimum_tokens=16, required=True, priority=80),
                ContextBudgetRequest(
                    "request_attachments",
                    24,
                    minimum_tokens=0,
                    required=False,
                    priority=10,
                ),
            ),
        )

        self.assertEqual(plan.total_tokens, 120)
        self.assertGreater(plan.overflow_tokens, 0)
        self.assertEqual(plan.allocation_for("stable_prefix").allocated_tokens, 32)
        self.assertEqual(plan.allocation_for("session_snapshot").allocated_tokens, 72)
        self.assertEqual(plan.allocation_for("loop_context").allocated_tokens, 16)
        self.assertIn("request_attachments", plan.omitted_layers)

    def test_retrieval_scheduler_prefers_work_item_linked_memory(self) -> None:
        scheduler = DeterministicRetrievalScheduler()
        requests = scheduler.schedule(
            session=self._session(),
            work_items=self._work_items(),
            recall_items=self._memories(),
            recent_loop_context=("user: recover the active current work after a gap",),
            token_budget=48,
            budget_plan=DeterministicBudgetManager().allocate(48, ()),
        )

        self.assertGreaterEqual(len(requests), 1)
        self.assertEqual(requests[0].evidence_refs, ("evidence-2",))
        self.assertIn("work-1", requests[0].work_item_ids)
        self.assertIn("active elephant work-linked evidence", requests[0].reason)
        self.assertIn("active elephant work-linked", requests[0].reason)
        self.assertIn("current-session evidence", requests[0].reason)

    def test_planner_and_renderer_surface_continuity_recovery(self) -> None:
        runtime = ContextRuntime(
            planner=LayeredContextPlanner(
                budget_manager=DeterministicBudgetManager(),
                summary_hook=DeterministicSummaryHook(),
                retrieval_scheduler=DeterministicRetrievalScheduler(),
            ),
            renderer=MarkdownPromptRenderer(),
            instruction_refs=("system:be concise", "system:preserve continuity"),
            total_tokens=120,
        )

        detailed = runtime.assemble_detailed(
            self._session(interruption_state="resume-after-gap"),
            self._work_items(),
            self._memories(),
            recent_loop_context=("user: continue the plan", "assistant: resumed state"),
            artifacts=("artifact-1",),
        )

        self.assertEqual(detailed.bundle.episode_id, "session-1")
        # Renderer switched from PascalCase class names to humane headings
        # and dropped the top-level `# Conversation context` + rationale
        # telemetry line (model had no use for that meta).
        # StateSnapshot stays telemetry-only.
        # ## LoopContext        → ## Recent turn context
        # ## RequestAttachments → ## Turn attachments
        # ## EpisodeReplay      → ## Recent turns
        # stable_prefix layer heading is suppressed because its content
        # carries its own `### Who you are` / `### Your own voice`
        # subheadings.
        self.assertNotIn("# Conversation context", detailed.rendered_prompt)
        self.assertNotIn("- rationale:", detailed.rendered_prompt)
        self.assertNotIn("## Session brief", detailed.rendered_prompt)
        self.assertNotIn("session-1", detailed.rendered_prompt)  # no record ids in prompt per R1
        self.assertIn("## Recent turn context", detailed.rendered_prompt)
        self.assertNotIn("## Episode context", detailed.rendered_prompt)
        self.assertIn("## Turn attachments", detailed.rendered_prompt)
        self.assertIn("## Recent turn context", detailed.bundle.prompt_envelope.loop_context)
        self.assertNotIn("ProceduralMemoryOverlay", detailed.rendered_prompt)
        self.assertNotIn("## Recent turns", detailed.rendered_prompt)
        # Summary / "reason:" telemetry header was dropped as prompt
        # noise. The `session_snapshot` key stays in `summary_by_layer`
        # for runtime audit but does not show up in the model-facing
        # rendered prompt any more.
        self.assertNotIn("Episode context summary", detailed.rendered_prompt)
        self.assertNotIn("reason: compress", detailed.rendered_prompt)
        self.assertIn("session_snapshot", detailed.summary_by_layer)
        self.assertGreaterEqual(len(detailed.retrieved_evidence_refs), 1)
        self.assertTrue(detailed.source_trace)
        self.assertIsNotNone(detailed.frame)
        assert detailed.frame is not None
        self.assertEqual(detailed.frame.session_snapshot.work_refs, ("work-1",))
        self.assertIn("evidence-2", detailed.frame.session_snapshot.evidence_refs)
        snapshot_trace = next(trace for trace in detailed.source_trace if trace.layer_name == "session_snapshot")
        self.assertIn("evidence-1", snapshot_trace.selected_refs)
        self.assertIn("evidence-2", snapshot_trace.selected_refs)
        self.assertIn("profile slice kept", snapshot_trace.reason)

    def test_source_trace_explains_compaction_and_retrieval(self) -> None:
        runtime = ContextRuntime(
            planner=LayeredContextPlanner(
                budget_manager=DeterministicBudgetManager(),
                summary_hook=DeterministicSummaryHook(),
                retrieval_scheduler=DeterministicRetrievalScheduler(),
            ),
            renderer=MarkdownPromptRenderer(),
            instruction_refs=("system:keep stable",),
            total_tokens=240,
        )

        recall_items = self._memories() + (
            RecallEvidence(
                evidence_id="evidence-4",
                episode_id="session-1",
                kind="note",
                content="A newer filler evidence keeps the long-running session realistic.",
                work_item_ids=(),
                tags=("filler",),
                created_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
            ),
        )
        detailed = runtime.assemble_detailed(
            self._session(interruption_state="resume-after-gap"),
            self._work_items(),
            recall_items,
            recent_loop_context=("user: continue the plan",),
        )

        snapshot_trace = next(trace for trace in detailed.source_trace if trace.layer_name == "session_snapshot")

        self.assertIn("evidence-1", snapshot_trace.selected_refs)
        self.assertIn("evidence-2", snapshot_trace.selected_refs)
        self.assertIn("evidence-4", snapshot_trace.selected_refs)
        self.assertIn("continuity recovery stayed explicit", snapshot_trace.reason)
        self.assertIn("evidence slice kept", snapshot_trace.reason)
        # Per R1, Source Trace is telemetry only — not rendered into the prompt.
        self.assertNotIn("Source Trace", detailed.rendered_prompt)

    def test_steady_selection_prefers_work_item_linked_memory_over_newer_filler(
        self,
    ) -> None:
        runtime = ContextRuntime(
            planner=LayeredContextPlanner(
                budget_manager=DeterministicBudgetManager(),
                summary_hook=DeterministicSummaryHook(),
                retrieval_scheduler=DeterministicRetrievalScheduler(),
            ),
            renderer=MarkdownPromptRenderer(),
            instruction_refs=("system:recover cleanly",),
            total_tokens=180,
        )
        recall_items = self._memories() + (
            RecallEvidence(
                evidence_id="evidence-4",
                episode_id="session-1",
                kind="note",
                content="Newest filler note with little durable value.",
                work_item_ids=(),
                tags=("filler",),
                created_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
            ),
            RecallEvidence(
                evidence_id="evidence-5",
                episode_id="session-1",
                kind="summary",
                content="Recovered durable state_focus after a long interruption.",
                work_item_ids=("work-1",),
                tags=("recovery",),
                created_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            ),
        )

        detailed = runtime.assemble_detailed(
            self._session(interruption_state="resume-after-gap"),
            self._work_items(),
            recall_items,
            recent_loop_context=("user: continue the plan",),
        )

        snapshot_trace = next(trace for trace in detailed.source_trace if trace.layer_name == "session_snapshot")
        self.assertIn("evidence-1", snapshot_trace.selected_refs)
        self.assertIn("evidence-2", snapshot_trace.selected_refs)
        self.assertIn("evidence-5", snapshot_trace.selected_refs)
        self.assertIn("profile slice kept", snapshot_trace.reason)

    def test_retrieval_layer_renders_selected_memory_and_reason(self) -> None:
        runtime = ContextRuntime(
            planner=LayeredContextPlanner(
                budget_manager=DeterministicBudgetManager(),
                summary_hook=DeterministicSummaryHook(),
                retrieval_scheduler=DeterministicRetrievalScheduler(),
            ),
            renderer=MarkdownPromptRenderer(),
            instruction_refs=("system:keep context inspectable",),
            total_tokens=180,
        )

        detailed = runtime.assemble_detailed(
            self._session(interruption_state="resume-after-gap"),
            self._work_items(),
            self._memories(),
            recent_loop_context=("user: recover the active current work after a gap",),
        )

        snapshot_layer = next(layer for layer in detailed.plan.layers if layer.layer_name == "session_snapshot")
        self.assertTrue(snapshot_layer.content)
        # Evidence-line prefix used to be `[summary]` — a bare taxonomic
        # tag. It is now a short natural label (`Summary:`, `Decision:`,
        # `Relationship note:`, ...).
        evidence_lines = tuple(
            line
            for line in snapshot_layer.content
            if "Summary: The last turn asked for recovery after a gap." in line and "why:" in line
        )
        self.assertTrue(evidence_lines)
        self.assertIn("active elephant work-linked evidence", evidence_lines[0])
        # Per R1, no evidence ids in evidence lines.
        self.assertNotIn("evidence-2", evidence_lines[0])
        prompt_snapshot = detailed.bundle.prompt_envelope.session_snapshot
        self.assertEqual(prompt_snapshot, "")

    def test_session_snapshot_summary_keeps_profile_values_legible_when_truncated(
        self,
    ) -> None:
        runtime = ContextRuntime(
            planner=LayeredContextPlanner(
                budget_manager=DeterministicBudgetManager(),
                summary_hook=DeterministicSummaryHook(),
                retrieval_scheduler=DeterministicRetrievalScheduler(),
            ),
            renderer=MarkdownPromptRenderer(),
            instruction_refs=("system:preserve continuity",),
            total_tokens=96,
        )

        detailed = runtime.assemble_detailed(
            self._session(),
            self._work_items(),
            self._memories(),
            profile_snapshot_refs=(
                "### What you know about the user",
                "- Preferred name: Xunzhuo",
                "- MBTI: INTJ",
                "- Pinned notes to keep in mind:",
                "  - " + ("keeps prompt continuity visible " * 8).strip(),
            ),
        )

        prompt_snapshot = detailed.bundle.prompt_envelope.session_snapshot
        self.assertNotIn("known user fields:", prompt_snapshot)
        self.assertNotIn("user summary:", prompt_snapshot)
        self.assertNotIn("Preferred name: Xunzhuo", prompt_snapshot)
        self.assertNotIn("MBTI: INTJ", prompt_snapshot)

    def test_steady_layer_prefers_work_item_linked_and_corrected_memory_over_blind_recency(
        self,
    ) -> None:
        runtime = ContextRuntime(
            planner=LayeredContextPlanner(
                budget_manager=DeterministicBudgetManager(),
                summary_hook=DeterministicSummaryHook(),
                retrieval_scheduler=DeterministicRetrievalScheduler(),
            ),
            renderer=MarkdownPromptRenderer(),
            instruction_refs=("system:keep continuity visible",),
            total_tokens=220,
        )

        recall_items = (
            RecallEvidence(
                evidence_id="evidence-1",
                episode_id="session-1",
                kind="decision",
                content="Older but active elephant work-linked release decision.",
                work_item_ids=("work-1",),
                tags=("continuity",),
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            RecallEvidence(
                evidence_id="evidence-2",
                episode_id="session-1",
                kind="semantic",
                content="Corrected operating truth for active current work.",
                work_item_ids=("work-1",),
                tags=("corrected",),
                created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
            RecallEvidence(
                evidence_id="evidence-3",
                episode_id="session-1",
                kind="note",
                content="Fresh filler evidence that should not dominate steady context.",
                work_item_ids=(),
                tags=("filler",),
                created_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            ),
            RecallEvidence(
                evidence_id="evidence-4",
                episode_id="session-1",
                kind="note",
                content="Another filler evidence that is newer but less relevant.",
                work_item_ids=(),
                tags=("filler",),
                created_at=datetime(2026, 1, 6, tzinfo=timezone.utc),
            ),
        )

        detailed = runtime.assemble_detailed(
            self._session(interruption_state="resume-after-gap"),
            self._work_items(),
            recall_items,
        )

        snapshot_trace = next(trace for trace in detailed.source_trace if trace.layer_name == "session_snapshot")
        self.assertIn("evidence-1", snapshot_trace.selected_refs)
        self.assertIn("evidence-2", snapshot_trace.selected_refs)
        self.assertNotEqual(snapshot_trace.selected_refs, ("evidence-2", "evidence-3", "evidence-4"))
        self.assertIn("profile slice kept", snapshot_trace.reason)

    def test_steady_summary_surfaces_retained_and_compacted_memory_refs(self) -> None:
        runtime = ContextRuntime(
            planner=LayeredContextPlanner(
                budget_manager=DeterministicBudgetManager(),
                summary_hook=DeterministicSummaryHook(),
                retrieval_scheduler=DeterministicRetrievalScheduler(),
            ),
            renderer=MarkdownPromptRenderer(),
            instruction_refs=("system:keep continuity visible",),
            total_tokens=180,
        )

        recall_items = (
            RecallEvidence(
                evidence_id="evidence-1",
                episode_id="session-1",
                kind="decision",
                content="Older but active elephant work-linked release decision.",
                work_item_ids=("work-1",),
                tags=("continuity",),
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            RecallEvidence(
                evidence_id="evidence-2",
                episode_id="session-1",
                kind="semantic",
                content="Corrected operating truth for active current work.",
                work_item_ids=("work-1",),
                tags=("corrected",),
                created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
            RecallEvidence(
                evidence_id="evidence-3",
                episode_id="session-1",
                kind="note",
                content="Fresh filler evidence that should not dominate steady context.",
                work_item_ids=(),
                tags=("filler",),
                created_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            ),
            RecallEvidence(
                evidence_id="evidence-4",
                episode_id="session-1",
                kind="note",
                content="Another filler evidence that is newer but less relevant.",
                work_item_ids=(),
                tags=("filler",),
                created_at=datetime(2026, 1, 6, tzinfo=timezone.utc),
            ),
        )

        detailed = runtime.assemble_detailed(
            self._session(interruption_state="resume-after-gap"),
            self._work_items(),
            recall_items,
        )

        snapshot_summary = detailed.summary_by_layer["session_snapshot"]
        # Per R1, summary content is human-readable — no evidence/work/profile ids.
        self.assertNotIn("evidence-1", snapshot_summary)
        self.assertNotIn("evidence-2", snapshot_summary)
        self.assertIn("steady:", snapshot_summary)
        self.assertIn("interruption: resume-after-gap", snapshot_summary)

    def test_replay_request_does_not_depend_on_removed_structured_evidence_copies(
        self,
    ) -> None:
        runtime = ContextRuntime(
            planner=LayeredContextPlanner(
                budget_manager=DeterministicBudgetManager(),
                summary_hook=DeterministicSummaryHook(),
                retrieval_scheduler=DeterministicRetrievalScheduler(),
            ),
            renderer=MarkdownPromptRenderer(),
            instruction_refs=("system:keep continuity visible",),
            total_tokens=320,
        )

        detailed = runtime.assemble_detailed(
            self._session(interruption_state="resume-after-gap"),
            self._work_items(),
            self._memories(),
            recent_loop_context=("user: replay the earlier decision path",),
            state_focus=self._state_focus(),
        )

        self.assertIsNotNone(detailed.frame)
        assert detailed.frame is not None
        self.assertEqual(detailed.frame.session_snapshot.work_refs, ("work-1",))
        self.assertIsNone(detailed.frame.replay_packet)
        self.assertNotIn("## Recent turns", detailed.rendered_prompt)
        self.assertNotIn("work-1", detailed.summary_by_layer["session_snapshot"])
        self.assertNotIn("work-1", detailed.rendered_prompt)

    def test_profile_state_focus_suppresses_work_slice_and_replay(self) -> None:
        runtime = ContextRuntime(
            planner=LayeredContextPlanner(
                budget_manager=DeterministicBudgetManager(),
                summary_hook=DeterministicSummaryHook(),
                retrieval_scheduler=DeterministicRetrievalScheduler(),
            ),
            renderer=MarkdownPromptRenderer(),
            instruction_refs=("system:keep continuity visible",),
            total_tokens=220,
        )

        detailed = runtime.assemble_detailed(
            self._session(),
            self._work_items(),
            self._memories(),
            recent_loop_context=("user: what tone should you use with me?",),
            state_focus=self._state_focus(
                focus_family="personal_model",
                focus_work_item_ids=(),
                continuity_signal="none",
                focus_scope="personal_model",
                context_budget="narrow",
            ),
        )

        self.assertIsNotNone(detailed.frame)
        assert detailed.frame is not None
        self.assertEqual(detailed.frame.session_snapshot.work_refs, ())
        self.assertNotIn(
            "work-slice: personal_model scope suppressed active elephant work items",
            detailed.frame.session_snapshot.content,
        )
        self.assertIsNone(detailed.frame.replay_packet)
        self.assertIn(
            "work slice suppressed by personal_model scope",
            detailed.summary_by_layer["session_snapshot"],
        )
        self.assertIn(
            "personal-model elephant focus suppresses unrelated work refs",
            detailed.plan.rationale,
        )


if __name__ == "__main__":
    unittest.main()
