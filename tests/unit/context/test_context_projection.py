# ruff: noqa: E402

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.context import projection as projection_module
from packages.context import (
    CheapToolResultPruner,
    EmbeddingProjectionRelevanceScorer,
    PROJECTION_EMBEDDING_TARGET,
    ProjectionCompactionPolicy,
    ProjectionSemanticAnchorStats,
    ProviderProjectionSummaryHook,
    SessionProjectionCompactor,
    queue_projection_history_embedding_backfill,
)
from packages.contracts import ContextBundle, ExecutionResult, PromptMessage
from packages.contracts.layers import Episode
from packages.contracts.runtime import PersonalModelRuntimeState
from packages.embeddings import EmbeddingHealth, EmbeddingPreloadEntry, EmbeddingPreloadState, EmbeddingVector


class _FakeProjectionEmbeddingService:
    def __init__(self, *, loaded: bool = True, auto_cache: bool = True, promote_pending_on_probe: bool = False) -> None:
        self.loaded = loaded
        self.auto_cache = auto_cache
        self.promote_pending_on_probe = promote_pending_on_probe
        self.queued_targets: list[tuple[str, int, str]] = []
        self.queued_entries: list[EmbeddingPreloadEntry] = []
        self.cache: dict[tuple[str, str, int], EmbeddingVector] = {}
        self.pending_keys: set[tuple[str, str, int]] = set()
        self.embed_calls = 0
        self.embed_text_calls = 0

    def health(self) -> EmbeddingHealth:
        return EmbeddingHealth(
            provider_id="elephant-local-embed",
            model_id="llm-semantic-router/elephant-embed",
            status="ready" if self.loaded else "pending",
            summary="loaded" if self.loaded else "cold",
            metadata={"runtime_state": "loaded" if self.loaded else "cold"},
        )

    def queue_backfill(self, *, target: str, entries, latency_mode: str = "balanced", provider_id: str | None = None):
        del provider_id
        queued_entries = tuple(entries)
        self.queued_targets.append((target, len(queued_entries), latency_mode))
        self.queued_entries.extend(queued_entries)
        if not self.auto_cache:
            return EmbeddingPreloadState(
                provider_id="elephant-local-embed",
                model_id="llm-semantic-router/elephant-embed",
                status="steadying",
                summary="queued",
                ready_dimensions=(64,),
                pending_targets=(target,),
            )
        for index, entry in enumerate(queued_entries):
            vector_index = 0 if entry.metadata.get("kind") == "query" or "database" in entry.text else 1
            self.cache[(target, entry.cache_key, 64)] = _unit_vector(64, index=vector_index, source_text=entry.text, text_index=index)
        return EmbeddingPreloadState(
            provider_id="elephant-local-embed",
            model_id="llm-semantic-router/elephant-embed",
            status="ready",
            summary="queued",
            ready_dimensions=(64,),
            pending_targets=(),
        )

    def cached_vector(self, *, target: str, cache_key: str, dimensions: int, provider_id: str | None = None):
        del provider_id
        return self.cache.get((target, cache_key, dimensions))

    def pending_vector(self, *, target: str, cache_key: str, dimensions: int, provider_id: str | None = None) -> bool:
        del provider_id
        key = (target, cache_key, dimensions)
        if key not in self.pending_keys:
            return False
        if self.promote_pending_on_probe:
            self.cache[key] = _unit_vector(dimensions, index=0, source_text=cache_key)
            self.pending_keys.remove(key)
        return True

    def embed(self, *args, **kwargs):
        del args, kwargs
        self.embed_calls += 1
        raise AssertionError("projection compaction must not synchronously embed")

    def embed_text(self, *args, **kwargs):
        del args, kwargs
        self.embed_text_calls += 1
        raise AssertionError("projection precompute must not synchronously embed query text")


class _FailingProjectionEmbeddingService(_FakeProjectionEmbeddingService):
    def cached_vector(self, **kwargs):
        del kwargs
        raise RuntimeError("cache lookup failed")

    def pending_vector(self, **kwargs) -> bool:
        del kwargs
        raise RuntimeError("pending lookup failed")

    def queue_backfill(self, **kwargs):
        del kwargs
        raise RuntimeError("queue failed")


class _QueueFailingProjectionEmbeddingService(_FakeProjectionEmbeddingService):
    def queue_backfill(self, **kwargs):
        del kwargs
        raise RuntimeError("queue failed")


class _HealthFailingProjectionEmbeddingService(_FakeProjectionEmbeddingService):
    def health(self) -> EmbeddingHealth:
        raise RuntimeError("health failed")


def _unit_vector(dimensions: int, *, index: int, source_text: str, text_index: int = 0) -> EmbeddingVector:
    return EmbeddingVector(
        text_index=text_index,
        provider_id="elephant-local-embed",
        model_id="llm-semantic-router/elephant-embed",
        dimensions=dimensions,
        values=tuple(1.0 if position == index else 0.0 for position in range(dimensions)),
        source_text=source_text,
    )


def _queued_entry(service: _FakeProjectionEmbeddingService, *, kind: str, contains: str) -> EmbeddingPreloadEntry:
    for entry in service.queued_entries:
        if entry.metadata.get("kind") == kind and contains in entry.text:
            return entry
    raise AssertionError(f"missing queued entry kind={kind} contains={contains}")


class SessionProjectionCompactorTest(unittest.TestCase):
    def test_projection_token_estimation_logs_tiktoken_failure(self) -> None:
        class BrokenEncoding:
            def encode(self, _text: str) -> list[int]:
                raise RuntimeError("tokenizer failed")

        previous_encoding = projection_module._TIKTOKEN_ENCODING
        previous_use_tiktoken = projection_module._USE_TIKTOKEN
        projection_module._TIKTOKEN_ENCODING = BrokenEncoding()
        projection_module._USE_TIKTOKEN = True
        try:
            with self.assertLogs("packages.context.projection", level="DEBUG") as captured:
                estimate = projection_module.estimate_projection_tokens("hello world")
        finally:
            projection_module._TIKTOKEN_ENCODING = previous_encoding
            projection_module._USE_TIKTOKEN = previous_use_tiktoken

        self.assertGreater(estimate, 0)
        rendered_logs = "\n".join(captured.output)
        self.assertIn("Tiktoken encode failed", rendered_logs)
        self.assertIn("tokenizer failed", rendered_logs)

    def test_embedding_projection_scorer_logs_cache_lookup_failures(self) -> None:
        service = _FailingProjectionEmbeddingService(loaded=True, auto_cache=False)
        scorer = EmbeddingProjectionRelevanceScorer(service)

        with self.assertLogs("packages.context.projection", level="DEBUG") as captured:
            result = scorer.rank(
                query="database migration decision",
                candidates=("database migration decision",),
                limit=1,
            )

        self.assertEqual(result, ())
        rendered_logs = "\n".join(captured.output)
        self.assertIn("Projection query cached-vector lookup failed", rendered_logs)
        self.assertIn("Projection query pending-vector lookup failed", rendered_logs)
        self.assertIn("Projection candidate cached-vector lookup failed", rendered_logs)

    def test_projection_history_backfill_logs_queue_failure(self) -> None:
        service = _QueueFailingProjectionEmbeddingService(loaded=True, auto_cache=False)
        messages = (
            PromptMessage(role="user", content="database migration decision"),
            PromptMessage(role="assistant", content="use a bounded WAL retry"),
        )

        with self.assertLogs("packages.context.projection", level="DEBUG") as captured:
            state = queue_projection_history_embedding_backfill(
                service,
                messages=messages,
                thread_focus="database migration",
            )

        self.assertIsNone(state)
        rendered_logs = "\n".join(captured.output)
        self.assertIn("Projection history embedding backfill queue failed", rendered_logs)
        self.assertIn("queue failed", rendered_logs)

    def test_projection_history_backfill_logs_health_failure(self) -> None:
        service = _HealthFailingProjectionEmbeddingService(loaded=True, auto_cache=False)
        messages = (PromptMessage(role="user", content="database migration decision"),)

        with self.assertLogs("packages.context.projection", level="DEBUG") as captured:
            state = queue_projection_history_embedding_backfill(
                service,
                messages=messages,
                thread_focus="database migration",
            )

        self.assertIsNone(state)
        rendered_logs = "\n".join(captured.output)
        self.assertIn("Projection embedding health check failed", rendered_logs)
        self.assertIn("health failed", rendered_logs)

    def test_default_projection_policy_compacts_at_sixty_percent(self) -> None:
        policy = ProjectionCompactionPolicy()

        self.assertEqual(policy.trigger_tokens(128_000), 76_800)
        self.assertEqual(policy.target_tokens(128_000), 17_920)
        self.assertEqual(policy.tail_tokens(128_000), 15_360)

    def test_cheap_tool_result_pruner_marks_old_tool_payloads(self) -> None:
        pruned = CheapToolResultPruner().prune_line(
            "tool: tool.web.search arguments: query=agent outcome: ok summary: " + ("result " * 120),
            max_chars=180,
        )

        self.assertIn("tool-result-pruned", pruned)
        self.assertIn("tool.web.search", pruned)
        self.assertLess(len(pruned), 220)

    def test_compaction_preserves_head_and_tail_while_summarizing_middle(self) -> None:
        messages = tuple(
            PromptMessage(
                role="user" if index % 2 == 0 else "assistant",
                content=(
                    f"completed request {index} " + ("payload " * 200)
                    if index % 2 == 0
                    else f"completed response {index} " + ("implementation validation " * 200)
                ),
            )
            for index in range(36)
        )
        compactor = SessionProjectionCompactor(
            policy=ProjectionCompactionPolicy(
                minimum_trigger_tokens=1,
                minimum_target_tokens=1,
                protected_head_lines=2,
                protected_tail_lines=4,
            )
        )

        projection = compactor.compact_messages(
            messages=messages,
            thread_focus="Implement prompt projection compaction",
            total_tokens=1024,
            reason="preflight",
        )

        self.assertTrue(projection.result.compacted)
        self.assertIn("CONTEXT COMPACTION - REFERENCE ONLY", projection.summary)
        self.assertIn("## Completed background", projection.summary)
        self.assertEqual(projection.messages[:2], messages[:2])
        self.assertEqual(projection.messages[-4:], messages[-4:])
        self.assertLess(len(projection.messages), len(messages))
        self.assertEqual(projection.result.compacted_line_count, len(messages) - len(projection.messages))

    def test_message_compaction_preserves_roles_and_tool_results_in_tail(self) -> None:
        messages = tuple(
            PromptMessage(role="user", content=f"completed request {index} " + ("payload " * 100))
            if index % 3 == 0
            else PromptMessage(role="assistant", content=f"completed response {index} " + ("implementation " * 100))
            if index % 3 == 1
            else PromptMessage(
                role="tool",
                content=f"tool result payload {index} " + ("detail " * 200),
                tool_call_id=f"call-{index}",
                tool_name="tool.web.search",
            )
            for index in range(30)
        )
        compactor = SessionProjectionCompactor(
            policy=ProjectionCompactionPolicy(
                minimum_trigger_tokens=1,
                minimum_target_tokens=1,
                protected_head_lines=2,
                protected_tail_lines=5,
            )
        )

        projection = compactor.compact_messages(
            messages=messages,
            thread_focus="Keep role-preserved history",
            total_tokens=1024,
            reason="preflight",
        )

        self.assertTrue(projection.result.compacted)
        self.assertEqual(tuple(message.role for message in projection.messages[:2]), ("user", "assistant"))
        self.assertEqual(projection.messages[-1].role, "tool")
        self.assertEqual(projection.messages[-1].tool_call_id, "call-29")
        self.assertIn("CONTEXT COMPACTION - REFERENCE ONLY", projection.summary)

    def test_tail_compaction_keeps_tool_call_groups_atomic(self) -> None:
        messages = (
            PromptMessage(role="user", content="start"),
            *tuple(PromptMessage(role="assistant", content=f"older answer {index}") for index in range(8)),
            PromptMessage(
                role="assistant",
                content="calling search",
                tool_calls=({"id": "call-live", "name": "tool.web.search"},),
            ),
            PromptMessage(
                role="tool",
                content="fresh tool result",
                tool_call_id="call-live",
                tool_name="tool.web.search",
            ),
        )
        compactor = SessionProjectionCompactor(
            policy=ProjectionCompactionPolicy(
                minimum_trigger_tokens=16,
                minimum_target_tokens=16,
                minimum_tail_tokens=1,
                protected_head_lines=1,
                protected_tail_lines=1,
            )
        )

        projection = compactor.compact_messages(
            messages=messages,
            thread_focus="tool search",
            total_tokens=1024,
            reason="provider-overflow",
            force=True,
        )

        self.assertTrue(projection.result.compacted)
        self.assertEqual(tuple(message.role for message in projection.messages[-2:]), ("assistant", "tool"))
        self.assertEqual(projection.messages[-2].tool_calls[0]["id"], "call-live")
        self.assertEqual(projection.messages[-1].tool_call_id, "call-live")

    def test_usage_force_can_summarize_a_single_oversized_completed_turn(self) -> None:
        messages = (
            PromptMessage(role="user", content="oversized completed request " + ("payload " * 5000)),
            PromptMessage(role="assistant", content="completed answer"),
        )
        compactor = SessionProjectionCompactor(
            policy=ProjectionCompactionPolicy(
                minimum_trigger_tokens=16,
                minimum_target_tokens=16,
                minimum_tail_tokens=1,
                protected_head_lines=2,
                protected_tail_lines=10,
            )
        )

        projection = compactor.compact_messages(
            messages=messages,
            thread_focus="completed oversized request",
            total_tokens=1024,
            reason="usage",
            force=True,
        )

        self.assertTrue(projection.result.compacted)
        self.assertEqual(projection.messages, (messages[-1],))
        self.assertIn("CONTEXT COMPACTION - REFERENCE ONLY", projection.summary)
        self.assertEqual(projection.result.compacted_line_count, 1)

    def test_im_compaction_uses_burst_tail_without_protecting_old_head(self) -> None:
        base = datetime(2026, 5, 9, 8, 0, tzinfo=timezone.utc)
        messages = (
            PromptMessage(role="user", content="morning topic", metadata={"projection_surface": "im", "created_at": base.isoformat()}),
            PromptMessage(role="assistant", content="morning reply", metadata={"projection_surface": "im", "created_at": (base + timedelta(minutes=1)).isoformat()}),
            PromptMessage(role="user", content="evening topic", metadata={"projection_surface": "im", "created_at": (base + timedelta(hours=10)).isoformat()}),
            PromptMessage(role="assistant", content="evening reply", metadata={"projection_surface": "im", "created_at": (base + timedelta(hours=10, minutes=1)).isoformat()}),
        )
        compactor = SessionProjectionCompactor(
            policy=ProjectionCompactionPolicy(
                minimum_trigger_tokens=1,
                minimum_target_tokens=1,
                im_tail_window_seconds=3600,
                im_idle_gap_seconds=1800,
            )
        )

        projection = compactor.compact_messages(
            messages=messages,
            thread_focus="IM conversation",
            total_tokens=1024,
            reason="gateway-hygiene",
            force=True,
        )

        self.assertTrue(projection.result.compacted)
        self.assertEqual(projection.result.protected_head_count, 0)
        self.assertEqual(tuple(message.content for message in projection.messages), ("evening topic", "evening reply"))
        self.assertNotIn("morning topic", [message.content for message in projection.messages])

    def test_embedding_ranked_middle_anchor_stays_role_preserved(self) -> None:
        class _Scorer:
            def __init__(self) -> None:
                self.query = ""
                self.candidates: tuple[str, ...] = ()

            def rank(self, *, query: str, candidates: tuple[str, ...], limit: int) -> tuple[int, ...]:
                self.query = query
                self.candidates = candidates
                return (1,) if limit else ()

        scorer = _Scorer()
        messages = (
            PromptMessage(role="user", content="start"),
            PromptMessage(role="assistant", content="older unrelated answer"),
            PromptMessage(role="assistant", content="semantic anchor: database migration decision"),
            PromptMessage(role="assistant", content="older unrelated detail"),
            PromptMessage(role="assistant", content="older unrelated result"),
            PromptMessage(role="user", content="continue the database migration"),
        )
        compactor = SessionProjectionCompactor(
            policy=ProjectionCompactionPolicy(
                minimum_trigger_tokens=16,
                minimum_target_tokens=16,
                minimum_tail_tokens=1,
                protected_head_lines=1,
                protected_tail_lines=1,
                semantic_anchor_max_messages=1,
            ),
            relevance_scorer=scorer,
        )

        projection = compactor.compact_messages(
            messages=messages,
            thread_focus="active task: database migration; blockers: pending DBA approval; next step: run the final migration",
            total_tokens=64,
            reason="provider-overflow",
            force=True,
        )

        self.assertTrue(projection.result.compacted)
        self.assertIn("latest user query: continue the database migration", scorer.query)
        self.assertIn("state focus:", scorer.query)
        self.assertEqual(projection.result.compaction_query, scorer.query)
        self.assertEqual(projection.result.protected_ranges, ("head:0-0", "tail:5-5"))
        self.assertEqual(len(projection.result.selected_raw_ids), 1)
        self.assertTrue(projection.result.summary_hash)
        self.assertIn("semantic anchor: database migration decision", [message.content for message in projection.messages])

    def test_projection_embedding_backfill_queues_cached_turn_groups_after_runtime_is_loaded(self) -> None:
        service = _FakeProjectionEmbeddingService(loaded=True)
        messages = (
            PromptMessage(role="user", content="continue the database migration"),
            PromptMessage(role="assistant", content="semantic anchor: database migration decision"),
            PromptMessage(role="assistant", content="older unrelated answer"),
        )

        state = queue_projection_history_embedding_backfill(
            service,
            messages=messages,
            thread_focus="database migration",
        )

        self.assertIsNotNone(state)
        self.assertEqual(service.queued_targets, [(PROJECTION_EMBEDDING_TARGET, 4, "fast")])
        self.assertEqual(service.queued_entries[0].metadata["kind"], "query")
        self.assertIn("older unrelated answer", service.queued_entries[1].text)
        self.assertEqual(service.embed_calls, 0)
        self.assertEqual(service.embed_text_calls, 0)

    def test_projection_embedding_backfill_skips_cold_runtime_to_avoid_query_latency(self) -> None:
        service = _FakeProjectionEmbeddingService(loaded=False)

        state = queue_projection_history_embedding_backfill(
            service,
            messages=(PromptMessage(role="user", content="continue the database migration"),),
            thread_focus="database migration",
        )

        self.assertIsNone(state)
        self.assertEqual(service.queued_targets, [])
        self.assertEqual(service.embed_calls, 0)
        self.assertEqual(service.embed_text_calls, 0)

    def test_embedding_projection_scorer_reads_cache_without_sync_embedding(self) -> None:
        service = _FakeProjectionEmbeddingService(loaded=True)
        queue_projection_history_embedding_backfill(
            service,
            messages=(
                PromptMessage(role="user", content="continue the database migration"),
                PromptMessage(role="assistant", content="semantic anchor: database migration decision"),
            ),
            thread_focus="database migration",
        )
        scorer = EmbeddingProjectionRelevanceScorer(service)

        ranked = scorer.rank(
            query="database migration\ncontinue the database migration",
            candidates=(
                "assistant: semantic anchor: database migration decision",
                "assistant: unrelated build output",
            ),
            limit=1,
        )

        self.assertEqual(ranked, (0,))
        self.assertEqual(service.embed_calls, 0)
        self.assertEqual(service.embed_text_calls, 0)

    def test_embedding_projection_scorer_records_pending_and_missed_cache_state(self) -> None:
        service = _FakeProjectionEmbeddingService(loaded=True, auto_cache=False)
        queue_projection_history_embedding_backfill(
            service,
            messages=(
                PromptMessage(role="user", content="continue the database migration"),
                PromptMessage(role="assistant", content="semantic anchor: database migration decision"),
                PromptMessage(role="assistant", content="pending architecture detail"),
            ),
            thread_focus="database migration",
        )
        query_entry = _queued_entry(service, kind="query", contains="database migration")
        cached_entry = _queued_entry(service, kind="group", contains="database migration decision")
        pending_entry = _queued_entry(service, kind="group", contains="pending architecture detail")
        service.cache[(PROJECTION_EMBEDDING_TARGET, query_entry.cache_key, 64)] = _unit_vector(
            64,
            index=0,
            source_text=query_entry.text,
        )
        service.cache[(PROJECTION_EMBEDDING_TARGET, cached_entry.cache_key, 64)] = _unit_vector(
            64,
            index=0,
            source_text=cached_entry.text,
        )
        service.pending_keys.add((PROJECTION_EMBEDDING_TARGET, pending_entry.cache_key, 64))
        scorer = EmbeddingProjectionRelevanceScorer(service)

        ranked = scorer.rank(
            query="database migration\ncontinue the database migration",
            candidates=(
                "assistant: semantic anchor: database migration decision",
                "assistant: pending architecture detail",
                "assistant: never queued historical detail",
            ),
            limit=2,
        )

        self.assertEqual(ranked, (0,))
        self.assertIsInstance(scorer.last_stats, ProjectionSemanticAnchorStats)
        self.assertEqual(scorer.last_stats.cached_group_count, 1)
        self.assertEqual(scorer.last_stats.pending_group_count, 1)
        self.assertEqual(scorer.last_stats.missed_group_count, 1)
        self.assertEqual(service.embed_calls, 0)

    def test_embedding_projection_scorer_is_cache_first_and_non_blocking(self) -> None:
        service = _FakeProjectionEmbeddingService(loaded=True, auto_cache=False, promote_pending_on_probe=True)
        queue_projection_history_embedding_backfill(
            service,
            messages=(
                PromptMessage(role="user", content="continue the database migration"),
                PromptMessage(role="assistant", content="semantic anchor: database migration decision"),
            ),
            thread_focus="database migration",
        )
        query_entry = _queued_entry(service, kind="query", contains="database migration")
        pending_entry = _queued_entry(service, kind="group", contains="database migration decision")
        # Query vector is steady — scorer can read it instantly.
        service.cache[(PROJECTION_EMBEDDING_TARGET, query_entry.cache_key, 64)] = _unit_vector(
            64,
            index=0,
            source_text=query_entry.text,
        )
        # Candidate vector is still pending — the scorer must not block on it.
        service.pending_keys.add((PROJECTION_EMBEDDING_TARGET, pending_entry.cache_key, 64))

        import time as _time_module

        def _no_sleep(_seconds: float) -> None:
            raise AssertionError("scorer.rank must not block the hot path via time.sleep")

        original_sleep = _time_module.sleep
        _time_module.sleep = _no_sleep
        try:
            scorer = EmbeddingProjectionRelevanceScorer(service)
            ranked = scorer.rank(
                query="database migration\ncontinue the database migration",
                candidates=("assistant: semantic anchor: database migration decision",),
                limit=1,
            )
        finally:
            _time_module.sleep = original_sleep

        # Query was cached (contributes to hit), candidate is pending so no
        # semantic ranking is emitted this turn. The hot path stays fast and
        # the projection compactor falls back to its deterministic policy.
        self.assertEqual(ranked, ())
        self.assertEqual(scorer.last_stats.pending_group_count, 1)
        self.assertEqual(service.embed_calls, 0)
        self.assertIn(
            scorer.last_stats.vector_cache_status,
            {"hit", "miss-backfilled", "pending"},
        )

    def test_iterative_compaction_carries_previous_summary_as_reference(self) -> None:
        compactor = SessionProjectionCompactor(
            policy=ProjectionCompactionPolicy(
                minimum_trigger_tokens=32,
                minimum_target_tokens=32,
                protected_head_lines=1,
                protected_tail_lines=3,
            )
        )
        messages = tuple(
            PromptMessage(
                role="user",
                content=f"follow-up {index} about the active implementation topic with concrete detail",
            )
            for index in range(18)
        )

        projection = compactor.compact_messages(
            messages=messages,
            thread_focus="Active compaction work",
            previous_summary="Earlier summary: runtime snapshot already froze the prompt prefix.",
            total_tokens=1024,
            reason="provider-overflow",
            force=True,
        )

        self.assertTrue(projection.result.compacted)
        self.assertIn("## Relevant facts/events", projection.summary)
        self.assertIn("runtime snapshot already froze the prompt prefix", projection.summary)
        self.assertIn("## Handoff notes for recent tail", projection.summary)
        self.assertIn("follow-up 17", projection.summary)

    def test_provider_summary_hook_uses_model_and_preserves_reference_only_header(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def generate(self, **kwargs):
                self.calls.append(dict(kwargs))
                assert isinstance(kwargs["context"], ContextBundle)
                assert kwargs["model_role"] == "weak"
                return ExecutionResult(
                    execution_id="exec:summary",
                    episode_id="session-test",
                    outcome="ok",
                    summary="## Active State Focus\n- focus: Compact context safely",
                )

        provider = _Provider()
        now = datetime.now(timezone.utc)
        hook = ProviderProjectionSummaryHook(
            provider=provider,
            profile=PersonalModelRuntimeState(profile_id="profile-test", display_name="Elephant Agent", mode="companion"),
            session=Episode(
                episode_id="session-test",
                state_id="state:test",
                personal_model_id="profile-test",
                entry_surface="test",
                elephant_id="elephant-test",
                status="open",
                started_at=now,
                updated_at=now,
            ),
        )

        summary = hook.summarize(
            thread_focus="Compact context safely",
            previous_summary="",
            compacted_lines=("tool: tool.web.search arguments: q=x outcome: ok summary: many results",),
            protected_tail=("user: keep working on compaction",),
            token_budget=128,
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(summary.startswith("[CONTEXT COMPACTION - REFERENCE ONLY]"))
        self.assertIn("Compact context safely", summary)

    def test_provider_summary_hook_suppresses_stream_observer_during_internal_summary(self) -> None:
        streamed: list[str] = []

        class _Provider:
            def __init__(self) -> None:
                self._stream_observer = streamed.append

            def set_stream_observer(self, observer) -> None:
                self._stream_observer = observer

            def generate(self, **kwargs):
                if self._stream_observer is not None:
                    self._stream_observer("[CONTEXT COMPACTION - REFERENCE ONLY]\nleaked")
                return ExecutionResult(
                    execution_id="exec:summary",
                    episode_id="session-test",
                    outcome="ok",
                    summary="[CONTEXT COMPACTION - REFERENCE ONLY]\n## Active State Focus\n- focus: Compact quietly",
                )

        provider = _Provider()
        original_observer = provider._stream_observer
        now = datetime.now(timezone.utc)
        hook = ProviderProjectionSummaryHook(
            provider=provider,
            profile=PersonalModelRuntimeState(profile_id="profile-test", display_name="Elephant Agent", mode="companion"),
            session=Episode(
                episode_id="session-test",
                state_id="state:test",
                personal_model_id="profile-test",
                entry_surface="test",
                elephant_id="elephant-test",
                status="open",
                started_at=now,
                updated_at=now,
            ),
        )

        summary = hook.summarize(
            thread_focus="Compact quietly",
            previous_summary="",
            compacted_lines=("user: old request",),
            protected_tail=("assistant: done",),
            token_budget=128,
        )

        self.assertEqual(streamed, [])
        self.assertIs(provider._stream_observer, original_observer)
        self.assertIn("Compact quietly", summary)

    def test_provider_summary_hook_logs_provider_failure_before_fallback(self) -> None:
        class _Provider:
            def generate(self, **kwargs):
                del kwargs
                raise RuntimeError("provider unavailable")

        now = datetime.now(timezone.utc)
        hook = ProviderProjectionSummaryHook(
            provider=_Provider(),
            profile=PersonalModelRuntimeState(profile_id="profile-test", display_name="Elephant Agent", mode="companion"),
            session=Episode(
                episode_id="session-test",
                state_id="state:test",
                personal_model_id="profile-test",
                entry_surface="test",
                elephant_id="elephant-test",
                status="open",
                started_at=now,
                updated_at=now,
            ),
        )

        with self.assertLogs("packages.context.projection", level="DEBUG") as captured:
            summary = hook.summarize(
                thread_focus="Compact with fallback",
                previous_summary="",
                compacted_lines=("user: old request",),
                protected_tail=("assistant: done",),
                token_budget=128,
            )

        self.assertIn("Compact with fallback", summary)
        rendered_logs = "\n".join(captured.output)
        self.assertIn("Provider projection summary failed", rendered_logs)
        self.assertIn("provider unavailable", rendered_logs)


if __name__ == "__main__":
    unittest.main()
