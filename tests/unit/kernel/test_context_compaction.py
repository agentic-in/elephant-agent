import unittest
from types import SimpleNamespace

from packages.context import ContextProjectionCompactionResult
from packages.kernel.context_compaction import (
    ContextCompactionOutcome,
    compaction_step_metadata,
    episode_continuity_packet,
    projection_compaction_detail,
    retry_context_after_provider_overflow,
)
from packages.contracts.runtime import ContextBundle, PromptEnvelope


class ContextCompactionKernelTest(unittest.TestCase):
    def test_packet_and_step_metadata_include_compaction_audit_fields(self) -> None:
        request = SimpleNamespace(
            request_id="request-1",
            episode_id="episode-1",
            loop_id="loop-1",
            source_id="record-1",
        )
        result = ContextProjectionCompactionResult(
            compacted=True,
            reason="preflight",
            before_tokens=1800,
            after_tokens=620,
            before_line_count=80,
            after_line_count=12,
            summary="[CONTEXT COMPACTION - REFERENCE ONLY]\n## Active State Focus\n- focus: Ship the migration",
            protected_head_count=2,
            protected_tail_count=3,
            protected_ranges=("head:0-1", "tail:77-79"),
            compacted_line_count=68,
            selected_raw_ids=("group:abc123", "group:def456"),
            compaction_query=(
                "latest user query: continue the database migration\n"
                "active task: database migration\n"
                "blockers: pending DBA approval\n"
                "next step: run the final migration"
            ),
            summary_hash="deadbeefcafefeed",
            semantic_anchor_selected_count=2,
        )

        packet = episode_continuity_packet(
            request=request,
            result=result,
            source_step_ids=("step:1", "step:2"),
        )
        metadata = compaction_step_metadata(
            packet=packet,
            result=result,
            source_step_ids=("step:1", "step:2"),
        )
        detail = projection_compaction_detail(result)

        self.assertIn("protected_ranges=head:0-1, tail:77-79", packet.text)
        self.assertIn("selected_raw_ids=group:abc123, group:def456", packet.text)
        self.assertIn("summary_hash=deadbeefcafefeed", packet.text)
        self.assertEqual(metadata["source_step_ids"], "step:1, step:2")
        self.assertEqual(metadata["protected_ranges"], "head:0-1, tail:77-79")
        self.assertEqual(metadata["selected_raw_ids"], "group:abc123, group:def456")
        self.assertEqual(metadata["summary_hash"], "deadbeefcafefeed")
        self.assertIn(
            "latest user query: continue the database migration",
            metadata["compaction_query"],
        )
        self.assertIn("protected_ranges=head:0-1|tail:77-79", detail)
        self.assertIn("selected_raw=2", detail)
        self.assertIn("summary_hash=deadbeefcafefeed", detail)

    def test_retry_context_after_provider_overflow_returns_continuity_outcome(
        self,
    ) -> None:
        result = ContextProjectionCompactionResult(
            compacted=True,
            reason="provider-overflow",
            before_tokens=2048,
            after_tokens=768,
            before_line_count=90,
            after_line_count=18,
            summary="[CONTEXT COMPACTION - REFERENCE ONLY]\n## Active State Focus\n- focus: recover after overflow",
            protected_ranges=("head:0-1", "tail:87-89"),
            selected_raw_ids=("group:recover",),
            summary_hash="feedfacecafebeef",
        )
        assembled = ContextBundle(
            bundle_id="bundle:rebuilt",
            episode_id="episode-2",
            token_budget=4096,
            prompt_envelope=PromptEnvelope(frozen_prefix="FIRST PREFIX"),
            rendered_prompt="FIRST PREFIX",
        )

        class _ContextCapability:
            def __init__(self) -> None:
                self.flushed = False

            def force_projection_compaction(self, *, reason: str):
                self.reason = reason
                return result

            def flush_projection_cache(self) -> None:
                self.flushed = True

            def assemble(self, session, work_items, recall_items, state_focus=None):
                return assembled

        capability = _ContextCapability()
        stage_events: list[tuple[str, str]] = []

        def _stage(name: str, detail: str) -> None:
            stage_events.append((name, detail))

        def _context_for_generation(**kwargs):
            return kwargs["context"]

        outcome = retry_context_after_provider_overflow(
            error=RuntimeError("prompt is too long"),
            dependencies=SimpleNamespace(context=capability),
            request=SimpleNamespace(
                request_id="request-2",
                episode_id="episode-2",
                loop_id="loop-2",
                source_id="record-2",
            ),
            profile=SimpleNamespace(),
            session=SimpleNamespace(),
            state_focus=None,
            work_items=(),
            recall_items=(),
            decision=None,
            plan=None,
            continuity=None,
            stage=_stage,
            context_for_generation=_context_for_generation,
            recovery_scope_reason="test-scope",
            source_step_ids=("step:9",),
        )

        self.assertIsInstance(outcome, ContextCompactionOutcome)
        assert outcome is not None
        self.assertTrue(capability.flushed)
        self.assertIn("## EpisodeContinuityPacket", outcome.context.prompt_envelope.loop_context)
        self.assertIn("selected_raw_ids=group:recover", outcome.packet.text)
        self.assertTrue(any(name == "context-compact" for name, _detail in stage_events))


if __name__ == "__main__":
    unittest.main()
