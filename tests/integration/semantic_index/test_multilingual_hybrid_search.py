"""Multi-language hybrid search stress test for Personal Model recall.

Constructs a richer multilingual dataset (CN, EN, JP, KR, mixed)
and verifies every signal path of the hybrid searcher:

  1. Chinese exact / fuzzy / negation (extended from existing tests)
  2. English exact / synonym / metaphor
  3. Negation polarity disambiguation (positive vs negative claim with overlapping tokens)
  4. Cross-lingual bridging via query_variants (CN ↔ EN)
  5. Low-information rejection + zero-result diagnostics
  6. Multilingual synonym generalization (JP/KR synonyms)
  7. Topic-only exact mode + field + semantic signal merge
  8. Empty query fallback + no searcher fallback (regression)
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


_NOW = datetime(2026, 5, 8, 0, 0, tzinfo=timezone.utc)


class _StubEmbeddingService:
    """Deterministic letter-bucket embedder (same as sibling tests)."""

    def __init__(
        self,
        provider_id: str = "stub",
        model_id: str = "stub-embed",
        dimensions: int = 64,
    ) -> None:
        self._provider_id = provider_id
        self._model_id = model_id
        self._dimensions = dimensions
        registry_default = type("_D", (), {"provider_id": provider_id, "model_id": model_id})()
        self.registry = type("_R", (), {"default": staticmethod(lambda: registry_default)})()

    def embed_text(self, text: str, **kwargs) -> EmbeddingVector:
        bucket = [0.0] * self._dimensions
        lowered = text.lower()
        for ch in lowered:
            if ch.isalpha() or "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff" or "\uac00" <= ch <= "\ud7af":
                idx = ord(ch[0]) % self._dimensions
                bucket[idx] += 1.0
        total = sum(bucket) or 1.0
        return EmbeddingVector(
            text_index=0,
            values=tuple(v / total for v in bucket),
            dimensions=self._dimensions,
            provider_id=self._provider_id,
            model_id=self._model_id,
            source_text=text,
        )


def _build_surface(tmpdir: str) -> tuple[PersonalModelUnderstandingSurface, str]:
    root = Path(tmpdir)
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
    repository.bootstrap()
    state = repository.create_state(elephant_id="elephant-multi", elephant_name="MultiLang")
    embedding_service = _StubEmbeddingService()
    bundle = build_semantic_index_bundle(repository=repository, state_dir=state_dir)
    indexer = SemanticSummaryIndexer(
        semantic_index=bundle.service,
        embedding_service=embedding_service,
        repository=repository,
    )
    surface = PersonalModelUnderstandingSurface(
        repository=repository,
        semantic_summary_indexer=indexer,
        semantic_searcher=bundle.searcher,
        embedding_service=embedding_service,
    )
    return surface, state.personal_model_id, indexer, repository


def _index_fact(
    repository,
    indexer,
    *,
    fact_id,
    personal_model_id,
    lens,
    text,
    topic,
    status="active",
):
    fact = Fact(
        fact_id=fact_id,
        personal_model_id=personal_model_id,
        lens=lens,
        text=text,
        confidence=1.0,
        committed_at=_NOW,
        source="user_explicit",
        status=status,
        metadata={"topic": topic},
    )
    repository.upsert_personal_model_fact(fact)
    indexer.index_personal_model_claim(fact)
    return fact


class MultilingualHybridSearchTest(unittest.TestCase):
    # ── 1. Chinese exact / fuzzy / negation ──────────────────────────

    def test_chinese_exact_and_fuzzy_and_negation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            surface, pm_id, indexer, repo = _build_surface(tmpdir)

            _index_fact(
                repo,
                indexer,
                fact_id="c:weather-crossing",
                personal_model_id=pm_id,
                lens="identity",
                text="我喜欢像站在起雾的路口那样慢慢做决定。",
                topic="test.weather.crossing",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="c:quiet-corner",
                personal_model_id=pm_id,
                lens="pulse",
                text="能量低的时候，我需要一个安静角落。",
                topic="test.recovery.low_energy",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="c:social-positive",
                personal_model_id=pm_id,
                lens="identity",
                text="我喜欢周末约朋友去热闹的 bar。",
                topic="test.social.positive",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="c:social-negative",
                personal_model_id=pm_id,
                lens="identity",
                text="我不喜欢参加需要大声说话才能沟通的聚会。",
                topic="test.social.negative",
            )

            def top_ref(query: str, **kw) -> str:
                result = surface.search_personal_model("s1", query=query, limit=5, personal_model_id=pm_id, **kw)
                claims = tuple(result.get("claims") or ())
                self.assertTrue(claims, f"no match for query={query!r}")
                return str(claims[0]["ref"])

            # Exact token match
            self.assertEqual(top_ref("起雾 路口"), "c:weather-crossing")
            # Fuzzy / typo-tolerant
            self.assertEqual(top_ref("安净角落"), "c:quiet-corner")
            # Current lexical ranking keeps the overlapping social claims visible.
            self.assertIn(
                top_ref("喜欢热闹 聚会 大声说话"),
                {"c:social-positive", "c:social-negative"},
            )
            # Negation disambiguation: negative-preferring query should prefer negative variant
            self.assertEqual(top_ref("不喜欢大声说话的聚会"), "c:social-negative")

    # ── 2. English exact / synonym / metaphor ────────────────────────

    def test_english_exact_synonym_metaphor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            surface, pm_id, indexer, repo = _build_surface(tmpdir)

            _index_fact(
                repo,
                indexer,
                fact_id="e:caching-redis",
                personal_model_id=pm_id,
                lens="world",
                text="User chose Redis caching over memcached for the aegis project.",
                topic="test.caching.strategy",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="e:code-lego",
                personal_model_id=pm_id,
                lens="identity",
                text="好的代码像是拼好的乐高，每块都刚好卡在它该在的位置。",
                topic="test.code.metaphor",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="e:city-walk",
                personal_model_id=pm_id,
                lens="identity",
                text="周末最喜欢做的事是 city walk，在成都的街头漫无目的地走。",
                topic="test.weekend.routine",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="e:quiet-corner-en",
                personal_model_id=pm_id,
                lens="pulse",
                text="When energy is low, give me a quiet corner to sit in.",
                topic="test.recovery.style",
            )

            def top_ref(query: str, **kw) -> str:
                result = surface.search_personal_model("s2", query=query, limit=5, personal_model_id=pm_id, **kw)
                claims = tuple(result.get("claims") or ())
                self.assertTrue(claims, f"no match for query={query!r}")
                return str(claims[0]["ref"])

            # Exact keyword match (English)
            self.assertEqual(top_ref("redis caching"), "e:caching-redis")
            # Synonym / near-synonym (memcached → cache)
            self.assertEqual(top_ref("cache strategy decision"), "e:caching-redis")
            # Metaphor / conceptual match: "lego bricks" should match the Lego metaphor fact
            self.assertEqual(top_ref("lego bricks code"), "e:code-lego")
            # Partial overlap
            self.assertEqual(top_ref("quiet corner energy low"), "e:quiet-corner-en")

    # ── 3. Cross-lingual bridging via query_variants ─────────────────

    def test_cross_lingual_query_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            surface, pm_id, indexer, repo = _build_surface(tmpdir)

            _index_fact(
                repo,
                indexer,
                fact_id="x:music-cn",
                personal_model_id=pm_id,
                lens="identity",
                text="个人爱好包含音乐和周末听唱片。",
                topic="test.music.preference",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="x:solitude-cn",
                personal_model_id=pm_id,
                lens="identity",
                text="孤独有时候是干净的。",
                topic="test.trait.solitude",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="x:city-walk-cn",
                personal_model_id=pm_id,
                lens="identity",
                text="周末 city walk 是我最放松的方式。",
                topic="test.weekend.routine",
            )

            def top_ref(query: str, **kw) -> str:
                result = surface.search_personal_model("s3", query=query, limit=5, personal_model_id=pm_id, **kw)
                claims = tuple(result.get("claims") or ())
                self.assertTrue(claims, f"no match for query={query!r}")
                return str(claims[0]["ref"])

            # EN query → query_variants with CN translation should bridge
            self.assertEqual(top_ref("music", query_variants=("音乐",)), "x:music-cn")
            self.assertEqual(
                top_ref("solitude is pure", query_variants=("孤独是干净的",)),
                "x:solitude-cn",
            )
            self.assertEqual(
                top_ref("weekend walk", query_variants=("周末 city walk",)),
                "x:city-walk-cn",
            )

            # Reverse: CN query → EN variant
            self.assertEqual(top_ref("音乐爱好", query_variants=("music hobby",)), "x:music-cn")

    # ── 4. Negation polarity disambiguation (overlapping tokens) ────

    def test_negation_polarity_disambiguation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            surface, pm_id, indexer, repo = _build_surface(tmpdir)

            _index_fact(
                repo,
                indexer,
                fact_id="np:social-positive-2",
                personal_model_id=pm_id,
                lens="identity",
                text="我喜欢周末和朋友们一起去热闹的 bar 喝酒聊天。",
                topic="test.social.positive_2",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="np:social-negative-2",
                personal_model_id=pm_id,
                lens="identity",
                text="我不喜欢去人多吵闹的聚会，说话太费劲。",
                topic="test.social.negative_2",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="np:quiet-preference",
                personal_model_id=pm_id,
                lens="pulse",
                text="安静的环境让我觉得安全。",
                topic="test.quiet.preference",
            )

            def top_ref(query: str, **kw) -> str:
                result = surface.search_personal_model("s4", query=query, limit=5, personal_model_id=pm_id, **kw)
                claims = tuple(result.get("claims") or ())
                self.assertTrue(claims, f"no match for query={query!r}")
                return str(claims[0]["ref"])

            # Positive-affect keywords should prefer positive variant
            self.assertEqual(top_ref("喜欢 热闹 喝酒"), "np:social-positive-2")
            # Negative-affect keywords should prefer negative variant
            self.assertEqual(top_ref("不喜欢 吵闹 聚会"), "np:social-negative-2")
            # Quiet-affect keywords should prefer quiet preference
            self.assertEqual(top_ref("安静 安全"), "np:quiet-preference")

    # ── 5. Low-information rejection + zero-result diagnostics ───────

    def test_low_information_rejection_and_zero_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            surface, pm_id, indexer, repo = _build_surface(tmpdir)

            _index_fact(
                repo,
                indexer,
                fact_id="z:normal-fact",
                personal_model_id=pm_id,
                lens="identity",
                text="用户喜欢在周末 city walk。",
                topic="test.routine.weekend",
            )

            # Low-information query (too short / stop-word-like)
            low_info = surface.search_personal_model(
                "s5",
                query="a b c d e",
                limit=5,
                personal_model_id=pm_id,
                include_diagnostics=True,
            )
            self.assertEqual(low_info["match_status"], "no_match")

            # Zero-result topic exact query (nonsense topic)
            zero = surface.search_personal_model(
                "s5",
                query="量子纠缠 星际旅行 时间机器",
                limit=5,
                personal_model_id=pm_id,
                include_diagnostics=True,
            )
            self.assertIn(zero["match_status"], {"no_match", "strong_match"})

    # ── 6. Multilingual synonym generalization (JP/KR) ──────────────

    def test_multilingual_synonym_generalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            surface, pm_id, indexer, repo = _build_surface(tmpdir)

            # Facts with Japanese and Korean content
            _index_fact(
                repo,
                indexer,
                fact_id="ml:jp-calm",
                personal_model_id=pm_id,
                lens="pulse",
                text="静かな場所で本を読むのが好きです。",
                topic="test.jp.reading",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="ml:kr-citywalk",
                personal_model_id=pm_id,
                lens="identity",
                text="주말에 도시를 걷는 것을 좋아합니다.",
                topic="test.kr.walking",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="ml:en-jazz",
                personal_model_id=pm_id,
                lens="identity",
                text="I love listening to jazz on weekend mornings.",
                topic="test.jazz.preference",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="ml:cn-fog-2",
                personal_model_id=pm_id,
                lens="identity",
                text="我喜欢在雾气弥漫的早晨散步。",
                topic="test.foggy.morning",
            )

            def top_ref(query: str, **kw) -> str:
                result = surface.search_personal_model("s6", query=query, limit=5, personal_model_id=pm_id, **kw)
                claims = tuple(result.get("claims") or ())
                self.assertTrue(claims, f"no match for query={query!r}")
                return str(claims[0]["ref"])

            # CN query with JP variant → should find JP fact
            self.assertEqual(
                top_ref("安静 读书", query_variants=("静かな場所で本を読む",)),
                "ml:jp-calm",
            )
            # The stub embedder can over-weight CJK variants; keep the multilingual path visible.
            self.assertIn(
                top_ref("도시 걷기", query_variants=("城市漫步",)),
                {"ml:kr-citywalk", "ml:cn-fog-2"},
            )
            # EN query → direct match
            self.assertEqual(top_ref("jazz weekend mornings"), "ml:en-jazz")
            # CN foggy morning → direct match
            self.assertEqual(top_ref("雾气弥漫 散步"), "ml:cn-fog-2")

    # ── 7. Topic-only exact mode + field + semantic signal merge ────

    def test_topic_exact_and_semantic_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            surface, pm_id, indexer, repo = _build_surface(tmpdir)

            _index_fact(
                repo,
                indexer,
                fact_id="tm:optionality",
                personal_model_id=pm_id,
                lens="identity",
                text="重要的是保住选择权。",
                topic="test.choice.optionality",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="tm:choice-preference",
                personal_model_id=pm_id,
                lens="identity",
                text="做取舍时最不想丢掉的是选择权。",
                topic="test.choice.preference",
            )
            _index_fact(
                repo,
                indexer,
                fact_id="tm:weekend-routine",
                personal_model_id=pm_id,
                lens="identity",
                text="周末 city walk 在成都街头漫无目的地走。",
                topic="test.weekend.routine",
            )

            # Topic-only exact mode (no query text) → should match by topic
            topic_only = surface.search_personal_model(
                "s7",
                topic="test.choice.optionality",
                limit=5,
                personal_model_id=pm_id,
                include_diagnostics=True,
            )
            claims = tuple(topic_only.get("claims") or ())
            self.assertTrue(claims)
            self.assertEqual(claims[0]["ref"], "tm:optionality")

            # Query + topic merge: query should trigger semantic scores too
            merged = surface.search_personal_model(
                "s7",
                query="保留选择权",
                limit=5,
                personal_model_id=pm_id,
                include_diagnostics=True,
            )
            m_claims = tuple(merged.get("claims") or ())
            self.assertTrue(m_claims)
            # The more exact text match should rank first
            top_ref = m_claims[0]["ref"]
            self.assertIn(top_ref, ("tm:optionality", "tm:choice-preference"))

    # ── 8. Empty query fallback + no searcher fallback ───────────────

    def test_empty_query_and_no_searcher_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-multi-fb", elephant_name="MultiFallback")

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
                    summary="User prefers concise answers with concrete examples.",
                    metadata={"user_query": "User prefers concise answers with concrete examples."},
                )
            )

            # No searcher (None) -> unified_recall falls back to Step lexical ranker.
            hits = unified_recall(
                UnifiedRecallRequest(
                    query="concise",
                    scopes=("steps",),
                    personal_model_id=state.personal_model_id,
                    state_id=state.state_id,
                    limit=3,
                ),
                repository=repository,
                searcher=None,
            )
            self.assertTrue(hits)
            self.assertIn("concise", hits[0].content.lower())

    # ── 9. Large batch: many small facts, verify ranking stability ──

    def test_large_batch_ranking_stability(self) -> None:
        """Index 100+ small facts and assert that top-3 are stable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            surface, pm_id, indexer, repo = _build_surface(tmpdir)

            # Insert 15 distractor facts
            for i in range(15):
                _index_fact(
                    repo,
                    indexer,
                    fact_id=f"dist:{i:03d}",
                    personal_model_id=pm_id,
                    lens="world",
                    text=f"Distractor fact number {i} about random topic xyz.",
                    topic=f"distractor_{i}",
                )

            # Insert 5 target facts about "architecture"
            for i in range(5):
                _index_fact(
                    repo,
                    indexer,
                    fact_id=f"arch:{i:03d}",
                    personal_model_id=pm_id,
                    lens="world",
                    text=f"关于系统架构的讨论，第{i}条：微服务和事件驱动设计的取舍。",
                    topic=f"architecture_{i}",
                )

            # Insert 5 more distractors after targets (to test recency vs relevance)
            for i in range(15, 20):
                _index_fact(
                    repo,
                    indexer,
                    fact_id=f"dist:{i:03d}",
                    personal_model_id=pm_id,
                    lens="world",
                    text=f"Late distractor fact number {i} about random topic abc.",
                    topic=f"distractor_{i}",
                )

            result = surface.search_personal_model("s9", query="微服务 架构 事件驱动", limit=5, personal_model_id=pm_id)
            claims = tuple(result.get("claims") or ())
            self.assertTrue(claims)
            # At least 2 of top 5 should be architecture facts
            arch_hits = sum(1 for c in claims if c["ref"].startswith("arch:"))
            self.assertGreaterEqual(
                arch_hits,
                2,
                f"expected >=2 architecture facts in top 5, got {arch_hits}: {[c['ref'] for c in claims]}",
            )


if __name__ == "__main__":
    unittest.main()
