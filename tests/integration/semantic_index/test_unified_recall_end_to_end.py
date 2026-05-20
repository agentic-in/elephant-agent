"""Integration test: Task 1 + Task 2 wiring.

Episode close writes exit_summary into the durable semantic index
(Task 1). A later `unified_recall` call with `scope=episodes` recovers
it via the hybrid searcher (Task 2). This catches regressions in the
shared `SemanticIndexBundle` and proves the producer/consumer contract
holds end-to-end.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts import Episode, Fact, Loop, Step
from packages.embeddings import EmbeddingVector
from packages.evidence import (
    SemanticSummaryIndexer,
    UnifiedRecallRequest,
    build_semantic_index_bundle,
    unified_recall,
)
from packages.storage import RuntimeStorageRepository
from packages.understanding import PersonalModelUnderstandingSurface


_NOW = datetime(2026, 4, 30, 10, 0, tzinfo=timezone.utc)


class _StubEmbeddingService:
    """Deterministic letter-bucket embedder.

    Two texts that share many characters will map to similar vectors.
    Good enough to prove the vector signal path works end-to-end.
    """

    def __init__(self, provider_id: str = "stub", model_id: str = "stub-embed") -> None:
        self._provider_id = provider_id
        self._model_id = model_id
        self._dimensions = 64
        default = type("_D", (), {"provider_id": provider_id, "model_id": model_id})()
        self.registry = type("_R", (), {"default": staticmethod(lambda: default)})()

    def embed_text(self, text: str, *, request_id: str = "", task: str = "", latency_mode: str = "") -> EmbeddingVector:
        del request_id, task, latency_mode
        bucket = [0.0] * self._dimensions
        for ch in text.lower():
            if ch.isalpha():
                bucket[(ord(ch) - 97) % self._dimensions] += 1.0
        total = sum(bucket) or 1.0
        return EmbeddingVector(
            text_index=0,
            values=tuple(v / total for v in bucket),
            dimensions=self._dimensions,
            provider_id=self._provider_id,
            model_id=self._model_id,
            source_text=text,
        )


class _CountingEmbeddingService:
    def __init__(self) -> None:
        self.calls = 0

    def embed_text(self, text: str, **_: object) -> EmbeddingVector:
        self.calls += 1
        return EmbeddingVector(
            text_index=0,
            values=(1.0,),
            dimensions=1,
            provider_id="counting",
            model_id="counting",
            source_text=text,
        )


class UnifiedRecallEndToEndTest(unittest.TestCase):
    def test_episode_close_then_recall_finds_summary(self) -> None:
        """The main integration loop: producer → consumer consistency."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)

            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-aa", elephant_name="AA")

            bundle = build_semantic_index_bundle(repository=repository, state_dir=state_dir)
            indexer = SemanticSummaryIndexer(
                semantic_index=bundle.service,
                embedding_service=_StubEmbeddingService(),
                repository=repository,
            )

            closed = Episode(
                episode_id="episode-1",
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                entry_surface="cli",
                status="closed",
                started_at=_NOW,
                ended_at=_NOW,
                exit_summary="We decided to use Redis caching over memcached for the aegis project.",
                metadata={"topic": "caching strategy"},
            )
            self.assertIsNotNone(
                indexer.index_episode_exit(closed),
                "episode indexer must succeed on happy path",
            )

            # Now recall from a different "session context" — the point
            # is that unified_recall + searcher + bundle all agree on the
            # same durable file.
            request = UnifiedRecallRequest(
                query="redis caching",
                scopes=("episodes",),
                personal_model_id=state.personal_model_id,
                state_id=state.state_id,
                limit=3,
            )
            hits = unified_recall(
                request,
                repository=repository,
                searcher=bundle.searcher,
            )

        self.assertTrue(hits, "recall should surface the indexed episode summary")
        contents = " ".join(hit.content.lower() for hit in hits)
        self.assertIn("redis", contents)
        # Verify no IDs leak to the caller.
        for hit in hits:
            self.assertNotIn("episode:", hit.content.lower())
            self.assertNotIn("record:", hit.content.lower())

    def test_personal_model_search_uses_semantic_index(self) -> None:
        """Personal Model foreground search should use the hybrid semantic index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)

            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-aa", elephant_name="AA")
            embedding_service = _StubEmbeddingService()
            bundle = build_semantic_index_bundle(repository=repository, state_dir=state_dir)
            indexer = SemanticSummaryIndexer(
                semantic_index=bundle.service,
                embedding_service=embedding_service,
                repository=repository,
            )
            fact = Fact(
                fact_id="claim:semantic-review-style",
                personal_model_id=state.personal_model_id,
                lens="pulse",
                text="User prefers terse architecture critiques with concrete counterexamples.",
                confidence=1.0,
                committed_at=_NOW,
                source="user_explicit",
                status="active",
                metadata={"topic": "assistant.review.style", "reason": "user corrected the assistant"},
            )
            repository.upsert_personal_model_fact(fact)
            self.assertIsNotNone(indexer.index_personal_model_claim(fact))

            surface = PersonalModelUnderstandingSurface(
                repository=repository,
                semantic_summary_indexer=indexer,
                semantic_searcher=bundle.searcher,
                embedding_service=embedding_service,
            )
            result = surface.search_personal_model(
                "session-semantic-search",
                query="architecture critique examples",
                limit=3,
                personal_model_id=state.personal_model_id,
            )

        claims = tuple(result.get("claims") or ())
        self.assertTrue(claims)
        self.assertEqual(claims[0]["ref"], fact.fact_id)

    def test_personal_model_search_merges_fielded_unicode_fuzzy_and_alias_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-aa", elephant_name="AA")
            embedding_service = _StubEmbeddingService()
            bundle = build_semantic_index_bundle(repository=repository, state_dir=state_dir)
            indexer = SemanticSummaryIndexer(
                semantic_index=bundle.service,
                embedding_service=embedding_service,
                repository=repository,
            )
            facts = (
                Fact(
                    fact_id="claim:fog-crossing",
                    personal_model_id=state.personal_model_id,
                    lens="identity",
                    text="我喜欢像站在起雾的路口那样慢慢做决定。",
                    confidence=0.9,
                    committed_at=_NOW,
                    source="user_explicit",
                    status="active",
                    metadata={"topic": "test.weather.crossing"},
                ),
                Fact(
                    fact_id="claim:quiet-corner",
                    personal_model_id=state.personal_model_id,
                    lens="pulse",
                    text="能量低的时候，我需要一个安静角落。",
                    confidence=0.9,
                    committed_at=_NOW,
                    source="user_explicit",
                    status="active",
                    metadata={"topic": "test.recovery.low_energy"},
                ),
                Fact(
                    fact_id="claim:topic-only",
                    personal_model_id=state.personal_model_id,
                    lens="world",
                    text="The body deliberately omits the lookup key.",
                    confidence=0.9,
                    committed_at=_NOW,
                    source="user_explicit",
                    status="active",
                    metadata={"topic": "test.topic.t1"},
                ),
                Fact(
                    fact_id="claim:music-cn",
                    personal_model_id=state.personal_model_id,
                    lens="identity",
                    text="个人爱好包含音乐和周末听唱片。",
                    confidence=0.9,
                    committed_at=_NOW,
                    source="user_explicit",
                    status="active",
                    metadata={"topic": "test.music.preference"},
                ),
                Fact(
                    fact_id="claim:solitude-clean",
                    personal_model_id=state.personal_model_id,
                    lens="identity",
                    text="孤独有时候是干净的。",
                    confidence=0.9,
                    committed_at=_NOW,
                    source="user_explicit",
                    status="active",
                    metadata={"topic": "test.trait.solitude"},
                ),
                Fact(
                    fact_id="claim:choice",
                    personal_model_id=state.personal_model_id,
                    lens="identity",
                    text="重要的是保住选择权。",
                    confidence=0.9,
                    committed_at=_NOW,
                    source="user_explicit",
                    status="active",
                    metadata={"topic": "test.choice.optionality"},
                ),
                Fact(
                    fact_id="claim:social-negative",
                    personal_model_id=state.personal_model_id,
                    lens="identity",
                    text="我不喜欢参加需要大声说话才能沟通的聚会。",
                    confidence=0.9,
                    committed_at=_NOW,
                    source="user_explicit",
                    status="active",
                    metadata={"topic": "test.social.negative"},
                ),
                Fact(
                    fact_id="claim:social-positive",
                    personal_model_id=state.personal_model_id,
                    lens="identity",
                    text="我喜欢周末约朋友去热闹的 bar。",
                    confidence=0.9,
                    committed_at=_NOW,
                    source="user_explicit",
                    status="active",
                    metadata={"topic": "test.social.positive"},
                ),
            )
            for fact in facts:
                repository.upsert_personal_model_fact(fact)
                indexer.index_personal_model_claim(fact)
            surface = PersonalModelUnderstandingSurface(
                repository=repository,
                semantic_summary_indexer=indexer,
                semantic_searcher=bundle.searcher,
                embedding_service=embedding_service,
            )

            def top_ref(query: str, **kwargs) -> str:
                result = surface.search_personal_model(
                    "session-fielded-search",
                    query=query,
                    limit=5,
                    personal_model_id=state.personal_model_id,
                    **kwargs,
                )
                claims = tuple(result.get("claims") or ())
                self.assertTrue(claims, query)
                return str(claims[0]["ref"])

            self.assertEqual(top_ref("起雾 路口"), "claim:fog-crossing")
            self.assertEqual(top_ref("象站在起雾的路口"), "claim:fog-crossing")
            self.assertEqual(top_ref("安净角落"), "claim:quiet-corner")
            self.assertEqual(top_ref("", topic="test.topic.t1"), "claim:topic-only")
            self.assertEqual(top_ref("music", query_variants=("音乐",)), "claim:music-cn")
            self.assertEqual(top_ref("solitude is pure", query_variants=("孤独是干净的",)), "claim:solitude-clean")
            self.assertEqual(top_ref("保留选择权"), "claim:choice")
            self.assertIn(top_ref("喜欢热闹 聚会 大声说话"), {"claim:social-positive", "claim:social-negative"})
            self.assertEqual(top_ref("不喜欢大声说话的聚会"), "claim:social-negative")

            no_match = surface.search_personal_model(
                "session-fielded-search",
                query="a b c d e",
                limit=5,
                personal_model_id=state.personal_model_id,
                include_diagnostics=True,
            )
            self.assertEqual(no_match["match_status"], "no_match")
            self.assertEqual(no_match["claims"], ())

            diagnostics = surface.search_personal_model(
                "session-fielded-search",
                topic="test.topic.t1",
                limit=5,
                personal_model_id=state.personal_model_id,
                include_diagnostics=True,
            )
            self.assertEqual(diagnostics["match_status"], "strong_match")
            claim = tuple(diagnostics["claims"])[0]
            self.assertEqual(claim["ref"], "claim:topic-only")

    def test_empty_query_falls_back_to_recency(self) -> None:
        """When the query is empty, skip semantic search and use recency."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)

            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-aa", elephant_name="AA")
            bundle = build_semantic_index_bundle(repository=repository, state_dir=state_dir)
            indexer = SemanticSummaryIndexer(
                semantic_index=bundle.service,
                embedding_service=_StubEmbeddingService(),
                repository=repository,
            )
            episode = Episode(
                episode_id="episode-recent",
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                entry_surface="cli",
                status="closed",
                started_at=_NOW,
                ended_at=_NOW,
                exit_summary="Old topic summary.",
            )
            # Mirror the kernel path: persist Episode row first, then index.
            repository.upsert_episode(episode)
            indexer.index_episode_exit(episode)

            # Empty query → fall back to lexical recency path.
            hits = unified_recall(
                UnifiedRecallRequest(
                    query="",
                    scopes=("episodes",),
                    personal_model_id=state.personal_model_id,
                    state_id=state.state_id,
                    limit=3,
                ),
                repository=repository,
                searcher=bundle.searcher,
            )
        self.assertTrue(hits, "fallback path should still return candidates")

    def test_step_semantic_recall_filters_tool_execution_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-aa", elephant_name="AA")
            bundle = build_semantic_index_bundle(repository=repository, state_dir=state_dir)
            indexer = SemanticSummaryIndexer(
                semantic_index=bundle.service,
                embedding_service=_StubEmbeddingService(),
                repository=repository,
            )
            tool_step = Step(
                step_id="step:tool",
                loop_id="loop-1",
                episode_id="episode-1",
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                phase="acting",
                action="call_tool",
                status="completed",
                sequence=1,
                created_at=_NOW,
                summary="tool result says family power structure",
                metadata={"tool_name": "tool.conversation.search", "tool_result": "family power tool report"},
            )
            user_step = Step(
                step_id="step:user",
                loop_id="loop-1",
                episode_id="episode-1",
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                phase="observation",
                action="record_input",
                status="completed",
                sequence=2,
                created_at=_NOW,
                summary="source item ingested",
                metadata={"event_type": "turn.received", "user_query": "We discussed family power structure."},
            )
            repository.upsert_episode(
                Episode(
                    episode_id="episode-1",
                    state_id=state.state_id,
                    personal_model_id=state.personal_model_id,
                    entry_surface="cli",
                    status="closed",
                    started_at=_NOW,
                    ended_at=_NOW,
                )
            )
            repository.upsert_loop(
                Loop(
                    loop_id="loop-1",
                    episode_id="episode-1",
                    state_id=state.state_id,
                    personal_model_id=state.personal_model_id,
                    trigger_type="turn.received",
                    status="closed",
                    started_at=_NOW,
                    ended_at=_NOW,
                )
            )
            repository.upsert_step(tool_step)
            repository.upsert_step(user_step)
            self.assertIsNone(indexer.index_step(tool_step))
            self.assertIsNotNone(indexer.index_step(user_step))

            hits = unified_recall(
                UnifiedRecallRequest(
                    query="family power",
                    scopes=("steps",),
                    personal_model_id=state.personal_model_id,
                    state_id=state.state_id,
                    limit=5,
                ),
                repository=repository,
                searcher=bundle.searcher,
            )

        contents = "\n".join(hit.content for hit in hits)
        self.assertIn("family power structure", contents)
        self.assertNotIn("tool report", contents)

    def test_no_searcher_uses_lexical_fallback(self) -> None:
        """When no searcher is provided, unified_recall uses fallback ranker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)

            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-aa", elephant_name="AA")

            repository.upsert_episode(
                Episode(
                    episode_id="episode-fallback",
                    state_id=state.state_id,
                    personal_model_id=state.personal_model_id,
                    entry_surface="test",
                    status="open",
                    started_at=_NOW,
                    updated_at=_NOW,
                )
            )
            repository.upsert_loop(
                Loop(
                    loop_id="loop-fallback",
                    episode_id="episode-fallback",
                    state_id=state.state_id,
                    personal_model_id=state.personal_model_id,
                    trigger_type="turn.received",
                    status="closed",
                    started_at=_NOW,
                    ended_at=_NOW,
                )
            )
            repository.upsert_step(
                Step(
                    step_id="step-fallback",
                    loop_id="loop-fallback",
                    episode_id="episode-fallback",
                    state_id=state.state_id,
                    personal_model_id=state.personal_model_id,
                    phase="observation",
                    action="record_input",
                    status="completed",
                    sequence=1,
                    created_at=_NOW,
                    summary="User prefers concise answers with examples.",
                    metadata={"user_query": "User prefers concise answers with examples."},
                )
            )

            hits = unified_recall(
                UnifiedRecallRequest(
                    query="concise",
                    scopes=("steps",),
                    personal_model_id=state.personal_model_id,
                    state_id=state.state_id,
                    limit=3,
                ),
                repository=repository,
                searcher=None,  # force fallback
            )
        self.assertTrue(hits)
        self.assertIn("concise", hits[0].content.lower())

    def test_cold_embedding_runtime_does_not_embed_on_hot_path(self) -> None:
        """Unified recall must not synchronously load local embeddings when cold."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)

            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-aa", elephant_name="AA")
            repository.upsert_episode(
                Episode(
                    episode_id="episode-cold",
                    state_id=state.state_id,
                    personal_model_id=state.personal_model_id,
                    entry_surface="test",
                    status="open",
                    started_at=_NOW,
                    updated_at=_NOW,
                )
            )
            repository.upsert_loop(
                Loop(
                    loop_id="loop-cold",
                    episode_id="episode-cold",
                    state_id=state.state_id,
                    personal_model_id=state.personal_model_id,
                    trigger_type="turn.received",
                    status="closed",
                    started_at=_NOW,
                    ended_at=_NOW,
                )
            )
            repository.upsert_step(
                Step(
                    step_id="step-cold",
                    loop_id="loop-cold",
                    episode_id="episode-cold",
                    state_id=state.state_id,
                    personal_model_id=state.personal_model_id,
                    phase="observation",
                    action="record_input",
                    status="completed",
                    sequence=1,
                    created_at=_NOW,
                    summary="Cold recall should use lexical fallback.",
                    metadata={"user_query": "Cold recall should use lexical fallback."},
                )
            )

            bundle = build_semantic_index_bundle(repository=repository, state_dir=state_dir)
            embedding_service = _CountingEmbeddingService()
            cold_health = type("_Health", (), {"status": "ready", "metadata": {"runtime_state": "cold"}})()
            hits = unified_recall(
                UnifiedRecallRequest(
                    query="cold lexical",
                    scopes=("steps",),
                    personal_model_id=state.personal_model_id,
                    state_id=state.state_id,
                    limit=3,
                ),
                repository=repository,
                searcher=bundle.searcher,
                embedding_service=embedding_service,
                embedding_health_callable=lambda: cold_health,
            )

        self.assertEqual(embedding_service.calls, 0)
        self.assertTrue(hits)


if __name__ == "__main__":
    unittest.main()
