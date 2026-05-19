from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

import apps.cli.runtime_turns as runtime_turns
from packages.contracts import EventEnvelope, ExecutionResult
from packages.kernel import ReconciliationPipeline


class RuntimeTurnsReasoningPayloadTests(unittest.TestCase):
    def test_payload_with_turn_reasoning_stays_on_event_payload_not_structured_evidence_copy(
        self,
    ) -> None:
        outcome = SimpleNamespace(
            state=SimpleNamespace(next_step="", summary=""),
            execution=SimpleNamespace(
                reasoning="Inspect tool evidence before drafting the answer.",
                summary="Draft the answer.",
            ),
        )

        payload = runtime_turns._payload_with_turn_reasoning(
            {"message": "what happened"},
            outcome,
            decision_summary="Draft the answer.",
        )

        self.assertEqual(
            payload["reasoning_trace"],
            "Inspect tool evidence before drafting the answer.",
        )
        self.assertEqual(
            payload["raw_reasoning_trace"],
            "Inspect tool evidence before drafting the answer.",
        )
        self.assertEqual(
            payload["reasoning_summary"],
            "Inspect tool evidence before drafting the answer.",
        )
        self.assertEqual(payload["reasoning_provenance"], "provider.raw_trace")

        observation = ReconciliationPipeline().observe_turn(
            inbound_event=EventEnvelope(
                event_id="event:reasoning-trace",
                event_type="turn.received",
                episode_id="session-reasoning-trace",
                source="cli",
                payload=payload,
            ),
            execution=ExecutionResult(
                execution_id="execution:reasoning-trace",
                episode_id="session-reasoning-trace",
                outcome="ok",
                summary="Draft the answer.",
                reasoning="Inspect tool evidence before drafting the answer.",
            ),
            decision_summary="Draft the answer.",
            source="cli",
            profile_id="profile-companion",
            elephant_id="elephant-1",
        )

        self.assertEqual(
            observation.durable_events[0].payload["reasoning_trace"],
            "Inspect tool evidence before drafting the answer.",
        )
        self.assertIn("Step records", observation.summary)

    def test_payload_with_turn_reasoning_falls_back_to_decision_summary_when_trace_missing(
        self,
    ) -> None:
        outcome = SimpleNamespace(
            state=SimpleNamespace(next_step="Call the provider health check.", summary=""),
            execution=SimpleNamespace(
                reasoning="",
                summary="Call the provider health check.",
            ),
        )

        payload = runtime_turns._payload_with_turn_reasoning(
            {"message": "what should we do next"},
            outcome,
            decision_summary="Call the provider health check.",
        )

        self.assertNotIn("reasoning_trace", payload)
        self.assertEqual(payload["reasoning_summary"], "Call the provider health check.")
        self.assertEqual(payload["reasoning_provenance"], "runtime.decision_summary")


class RuntimeTurnsCompactionTests(unittest.TestCase):
    def test_reflect_compress_summary_allows_reflect_inside_sub_agent_runtime(
        self,
    ) -> None:
        runtime = SimpleNamespace(
            sub_agent_active=True,
            _load_session=mock.Mock(
                return_value=SimpleNamespace(
                    personal_model_id="pm-1",
                    state_id="state-1",
                )
            ),
        )
        outcome = SimpleNamespace(route_session_id="session-1")
        log = mock.Mock()

        def _fake_reflect(runtime_arg, _job, *, explicit_features, persist_result):
            self.assertFalse(runtime_arg.sub_agent_active)
            self.assertEqual(explicit_features, ("compress",))
            self.assertFalse(persist_result)
            return SimpleNamespace(summary="compressed summary")

        with mock.patch("apps.reflect.runner.run_reflect_agent", side_effect=_fake_reflect):
            summary, fallback_note = runtime_turns._reflect_compress_summary(
                runtime,
                outcome,
                frozen_epoch=SimpleNamespace(compacted_history_summary=""),
                to_summarize=(),
                tail=(),
                context_limit=4096,
                log=log,
            )

        self.assertEqual(summary, "compressed summary")
        self.assertEqual(fallback_note, "llm_failed_using_heuristic")
        self.assertTrue(runtime.sub_agent_active)


if __name__ == "__main__":
    unittest.main()
