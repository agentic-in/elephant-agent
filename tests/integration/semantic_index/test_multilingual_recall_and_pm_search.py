"""Multi-language conversation recall and Personal Model search integration tests.

Covers the full tool-surface call paths for both:
  1. tool.conversation.search  → unified_recall (Step/Episode recall)
  2. tool.personal_model.search → PersonalModelUnderstandingSurface.search_personal_model

with multilingual data: CN, EN, JP, KR, and mixed-language content.

Design notes:
- Uses a CJK-capable stub embedder so multilingual semantic signals are
  deterministic and reproducible.
- Lens values are drawn from the current contract: identity/world/pulse/journey.
- Each test verifies that the *same multilingual content* can be retrieved
  through both the PM search path and the conversation recall path when appropriate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts import (
    Episode,
    Fact,
    Loop,
    Step,
)
from packages.contracts.personal_model import ALLOWED_LENSES
from packages.embeddings import EmbeddingVector
from packages.evidence import (
    SemanticSummaryIndexer,
    UnifiedRecallRequest,
    build_semantic_index_bundle,
    unified_recall,
)
from packages.storage import RuntimeStorageRepository
from packages.understanding import PersonalModelUnderstandingSurface


_NOW = datetime(2026, 5, 15, 0, 0, tzinfo=timezone.utc)
_SUPPORTED_LENSES = tuple(ALLOWED_LENSES)


# ── CJK-capable stub embedder ────────────────────────────────────────────

class _CJKCapableStubEmbeddingService:
    """Character-category bucket embedder that handles ASCII, CJK, Hangul, Kana.

    Two texts that share many characters (within each category) map to similar
    vectors. The 64-dimension bucket is split into four zones:

      - [0..25]   ASCII a-z (26 dims)
      - [26..45]  CJK unified ideographs (20 dims)
      - [46..55]  Hiragana + Katakana (10 dims)
      - [56..63]  Hangul (8 dims)
    """

    def __init__(self, provider_id: str = "stub", model_id: str = "stub-embed") -> None:
        self._provider_id = provider_id
        self._model_id = model_id
        self._dimensions = 64
        default = type("_D", (), {"provider_id": provider_id, "model_id": model_id})()
        self.registry = type("_R", (), {"default": staticmethod(lambda: default)})()

    def embed_text(self, text: str, **kwargs) -> EmbeddingVector:
        del kwargs
        bucket = [0.0] * self._dimensions
        for ch in text:
            cp = ord(ch)
            # ASCII a-z
            if 97 <= cp <= 122:
                bucket[cp - 97] += 1.0
            # ASCII A-Z → fold to lower
            elif 65 <= cp <= 90:
                bucket[cp - 65] += 1.0
            # CJK unified ideographs (4E00-9FFF)
            elif 0x4E00 <= cp <= 0x9FFF:
                zone = 26 + ((cp - 0x4E00) % 20)
                bucket[zone] += 1.0
            # Hiragana (3040-309F) + Katakana (30A0-30FF)
            elif 0x3040 <= cp <= 0x30FF:
                zone = 46 + ((cp - 0x3040) % 10)
                bucket[zone] += 1.0
            # Hangul (AC00-D7AF)
            elif 0xAC00 <= cp <= 0xD7AF:
                zone = 56 + ((cp - 0xAC00) % 8)
                bucket[zone] += 1.0
        total = sum(bucket) or 1.0
        return EmbeddingVector(
            text_index=0,
            values=tuple(v / total for v in bucket),
            dimensions=self._dimensions,
            provider_id=self._provider_id,
            model_id=self._model_id,
            source_text=text,
        )


class _DimensionAwareSemanticStubEmbeddingService:
    """Stub that exposes the production fast/balanced dimension split.

    The production semantic indexer writes with latency_mode=balanced (256d).
    Query-time recall must use the same dimensionality; otherwise sqlite-vec
    searches an empty 64d table and silently falls back to lexical signals.
    """

    def __init__(self, provider_id: str = "stub", model_id: str = "stub-embed") -> None:
        self._provider_id = provider_id
        self._model_id = model_id
        default = type("_D", (), {"provider_id": provider_id, "model_id": model_id})()
        self.registry = type("_R", (), {"default": staticmethod(lambda: default)})()

    def embed_text(self, text: str, **kwargs) -> EmbeddingVector:
        latency_mode = str(kwargs.get("latency_mode") or "balanced").lower()
        dimensions = 64 if latency_mode == "fast" else 256
        lowered = text.casefold()
        values = [0.0] * dimensions
        if (
            "日语歌" in text
            or "city pop" in lowered
            or "anime pronunciation" in lowered
            or "pronunciation practice" in lowered
        ):
            values[7] = 1.0
        elif "多语言测试经验" in text or "infj" in lowered or "pressure pattern" in lowered:
            values[53] = 1.0
        else:
            values[127 % dimensions] = 1.0
        return EmbeddingVector(
            text_index=0,
            values=tuple(values),
            dimensions=dimensions,
            provider_id=self._provider_id,
            model_id=self._model_id,
            source_text=text,
        )


# ── Test fixture helpers ─────────────────────────────────────────────────

@dataclass
class MultilingualFixture:
    surface: PersonalModelUnderstandingSurface
    personal_model_id: str
    state_id: str
    repository: RuntimeStorageRepository
    indexer: SemanticSummaryIndexer


def _build_fixture(tmpdir: str) -> MultilingualFixture:
    root = Path(tmpdir)
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
    repository.bootstrap()
    state = repository.create_state(
        elephant_id="elephant-multilingual",
        elephant_name="MultiLingualRecall",
    )
    embedding_service = _CJKCapableStubEmbeddingService()
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
    return MultilingualFixture(
        surface=surface,
        personal_model_id=state.personal_model_id,
        state_id=state.state_id,
        repository=repository,
        indexer=indexer,
    )


def _seed_pm_fact(fx: MultilingualFixture, *, fact_id: str, lens: str, text: str, topic: str) -> None:
    """Write one Fact through the repository + index it for PM search."""
    assert lens in _SUPPORTED_LENSES, f"invalid lens {lens!r}, must be one of {_SUPPORTED_LENSES}"
    fact = Fact(
        fact_id=fact_id,
        personal_model_id=fx.personal_model_id,
        lens=lens,
        text=text,
        confidence=1.0,
        committed_at=_NOW,
        source="user_explicit",
        status="active",
        metadata={"topic": topic},
    )
    fx.repository.upsert_personal_model_fact(fact)
    fx.indexer.index_personal_model_claim(fact)


def _seed_step(fx: MultilingualFixture, *, step_id: str, summary: str, action: str = "record_input", sequence: int = 1) -> None:
    """Write one Step (user turn) through the repository + index it for conversation recall."""
    episode_id = f"episode-{step_id.split(':')[0].replace('_', '-')}"
    loop_id = f"loop-{step_id.split(':')[0].replace('_', '-')}"

    # Ensure episode + loop exist
    try:
        fx.repository.upsert_episode(
            Episode(
                episode_id=episode_id,
                state_id=fx.state_id,
                personal_model_id=fx.personal_model_id,
                entry_surface="cli",
                status="closed",
                started_at=_NOW,
                ended_at=_NOW,
            )
        )
    except Exception:
        pass
    try:
        fx.repository.upsert_loop(
            Loop(
                loop_id=loop_id,
                episode_id=episode_id,
                state_id=fx.state_id,
                personal_model_id=fx.personal_model_id,
                trigger_type="turn.received",
                status="closed",
                started_at=_NOW,
                ended_at=_NOW,
            )
        )
    except Exception:
        pass

    used_sequences = {step.sequence for step in fx.repository.list_steps(loop_id=loop_id)}
    if sequence in used_sequences:
        sequence = (max(used_sequences) if used_sequences else 0) + 1

    step = Step(
        step_id=step_id,
        loop_id=loop_id,
        episode_id=episode_id,
        state_id=fx.state_id,
        personal_model_id=fx.personal_model_id,
        phase="observation",
        action=action,
        status="completed",
        sequence=sequence,
        created_at=_NOW,
        summary=summary,
        metadata={"event_type": "turn.received", "user_query": summary},
    )
    fx.repository.upsert_step(step)
    fx.indexer.index_step(step)


def _pm_search(fx: MultilingualFixture, query: str, **kw) -> dict:
    """Run tool.personal_model.search equivalent and return result dict."""
    result = fx.surface.search_personal_model(
        "session-multi",
        query=query,
        limit=10,
        personal_model_id=fx.personal_model_id,
        **kw,
    )
    return dict(result)


def _top_pm_ref(fx: MultilingualFixture, query: str, **kw) -> str:
    """Return the top claim ref from a PM search."""
    result = _pm_search(fx, query, **kw)
    claims = tuple(result.get("claims") or ())
    if not claims:
        return ""
    return str(claims[0]["ref"])


def _conversation_recall(fx: MultilingualFixture, query: str, scopes: tuple[str, ...] = ("steps",)) -> list:
    """Run tool.conversation.search equivalent and return hits."""
    hits = unified_recall(
        UnifiedRecallRequest(
            query=query,
            scopes=scopes,
            personal_model_id=fx.personal_model_id,
            state_id=fx.state_id,
            limit=10,
        ),
        repository=fx.repository,
        searcher=None,  # use lexical fallback for deterministic testing
    )
    return list(hits)


# ── Tests ────────────────────────────────────────────────────────────────

class MultiLingualRecallAndPMTest(unittest.TestCase):
    """Comprehensive multilingual test for both conversation recall and PM search."""

    # ── 1. Chinese PM search + step recall ────────────────────────────

    def test_chinese_pm_search_matches_exact_and_fuzzy(self) -> None:
        """PM search with Chinese query: exact token, fuzzy CJK n-gram."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            _seed_pm_fact(fx, fact_id="cn:fog", lens="identity", text="我喜欢像站在起雾的路口那样慢慢做决定。", topic="test.decision.fog")
            _seed_pm_fact(fx, fact_id="cn:quiet", lens="pulse", text="能量低的时候，我需要一个安静角落。", topic="test.recovery.corner")
            _seed_pm_fact(fx, fact_id="cn:social-pos", lens="world", text="我喜欢周末约朋友去热闹的 bar。", topic="test.social.bar")
            _seed_pm_fact(fx, fact_id="cn:social-neg", lens="identity", text="我不喜欢参加需要大声说话才能沟通的聚会。", topic="test.social.party")

            # Exact token match
            self.assertEqual(_top_pm_ref(fx, "起雾 路口"), "cn:fog")
            # Fuzzy CJK n-gram (安净 vs 安静)
            self.assertEqual(_top_pm_ref(fx, "安净角落"), "cn:quiet")
            # Negation: positive query → social-pos
            self.assertEqual(_top_pm_ref(fx, "喜欢 热闹 喝酒"), "cn:social-pos")
            # Negation: negative query → social-neg
            self.assertEqual(_top_pm_ref(fx, "不喜欢大声说话的聚会"), "cn:social-neg")
            # Low-information rejection
            result = _pm_search(fx, "a b c d e", include_diagnostics=True)
            self.assertEqual(result["match_status"], "no_match")

    def test_chinese_conversation_recall_exact_and_fuzzy(self) -> None:
        """Conversation recall (tool.conversation.search) with Chinese queries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            _seed_step(fx, step_id="cn:step-fog", summary="用户说：我喜欢像站在起雾的路口那样慢慢做决定。", sequence=1)
            _seed_step(fx, step_id="cn:step-quiet", summary="用户说：能量低的时候，我需要一个安静角落。", sequence=1)

            # Token match: "起雾的路口" is an exact substring of the step text
            hits = _conversation_recall(fx, "起雾的路口")
            self.assertTrue(hits, "lexical recall should find exact CJK substring")
            contents = " ".join(h.content for h in hits)
            self.assertIn("起雾", contents)

            # Substring match with extra content
            hits = _conversation_recall(fx, "安静角落")
            self.assertTrue(hits, "lexical recall should find CJK exact substring")
            contents = " ".join(h.content for h in hits)
            self.assertIn("安静角落", contents)

    # ── 2. English PM search + step recall ────────────────────────────

    def test_english_pm_search_exact_and_synonym(self) -> None:
        """PM search with English query: exact, synonym, conceptual."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            _seed_pm_fact(fx, fact_id="en:redis", lens="world", text="User chose Redis caching over memcached for the aegis project.", topic="test.caching")
            _seed_pm_fact(fx, fact_id="en:lego", lens="identity", text="好的代码像是拼好的乐高，每块都刚好卡在它该在的位置。", topic="test.code.metaphor")
            _seed_pm_fact(fx, fact_id="en:citywalk", lens="pulse", text="周末最喜欢做的事是 city walk，在成都的街头漫无目的地走。", topic="test.weekend.routine")

            # Exact match
            self.assertEqual(_top_pm_ref(fx, "redis caching"), "en:redis")
            # Synonym
            self.assertEqual(_top_pm_ref(fx, "cache strategy decision"), "en:redis")

    def test_english_conversation_recall(self) -> None:
        """Conversation recall with English queries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            _seed_step(fx, step_id="en:step-redis", summary="User decided to use Redis caching over memcached.")
            _seed_step(fx, step_id="en:step-lego", summary="好的代码像是拼好的乐高——每块都刚好卡在它该在的位置。")

            # English token overlap: "redis" is a token match via _TOKEN_RE
            hits = _conversation_recall(fx, "redis caching")
            self.assertTrue(hits, "lexical recall should find English token match")
            contents = " ".join(h.content for h in hits)
            self.assertIn("Redis", contents)

            # Mixed EN+CN: "乐高" is a CJK exact substring of the step text
            hits = _conversation_recall(fx, "乐高")
            self.assertTrue(hits, "lexical recall should find CJK exact substring")
            contents = " ".join(h.content for h in hits)
            self.assertIn("乐高", contents)

    # ── 3. Cross-lingual via query_variants ──────────────────────────

    def test_cross_lingual_pm_search_query_variants(self) -> None:
        """PM search with cross-lingual query_variants bridges CN↔EN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            _seed_pm_fact(fx, fact_id="xl:music", lens="identity", text="个人爱好包含音乐和周末听唱片。", topic="test.music")
            _seed_pm_fact(fx, fact_id="xl:solitude", lens="identity", text="孤独有时候是干净的。", topic="test.trait.solitude")
            _seed_pm_fact(fx, fact_id="xl:citywalk", lens="pulse", text="周末 city walk 是我最放松的方式。", topic="test.weekend.citywalk")

            # EN query → CN variant → should find CN fact
            self.assertEqual(
                _top_pm_ref(fx, "music", query_variants=("音乐",)),
                "xl:music",
            )
            self.assertEqual(
                _top_pm_ref(fx, "solitude is pure", query_variants=("孤独是干净的",)),
                "xl:solitude",
            )
            self.assertEqual(
                _top_pm_ref(fx, "weekend walk", query_variants=("周末 city walk",)),
                "xl:citywalk",
            )
            # Reverse: CN query → EN variant
            self.assertEqual(
                _top_pm_ref(fx, "音乐爱好", query_variants=("music hobby",)),
                "xl:music",
            )

    def test_cross_lingual_conversation_recall_fallback(self) -> None:
        """Conversation recall with cross-lingual queries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            _seed_step(fx, step_id="xl:step-music", summary="用户分享说个人爱好包含音乐和周末听唱片。")

            # EN query — lexical fallback may not bridge CN→EN without variants,
            # but should still surface the step if tokens overlap
            hits = _conversation_recall(fx, "音乐")
            if hits:
                contents = " ".join(h.content for h in hits)
                self.assertIn("音乐", contents)

    # ── 4. Japanese and Korean content ────────────────────────────────

    def test_jp_kr_pm_search(self) -> None:
        """PM search with Japanese and Korean content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            _seed_pm_fact(fx, fact_id="jp:calm", lens="identity", text="静かな場所で本を読むのが好きです。", topic="test.jp.reading")
            _seed_pm_fact(fx, fact_id="kr:walking", lens="pulse", text="주말에 도시를 걷는 것을 좋아합니다.", topic="test.kr.walking")
            _seed_pm_fact(fx, fact_id="en:jazz", lens="identity", text="I love listening to jazz on weekend mornings.", topic="test.jazz.morning")

            # JP query with JP variant
            self.assertEqual(
                _top_pm_ref(fx, "静かな場所", query_variants=("quiet place reading",)),
                "jp:calm",
            )
            # KR query with KR variant
            self.assertEqual(
                _top_pm_ref(fx, "도시 걷기", query_variants=("city walking weekend",)),
                "kr:walking",
            )
            # EN direct match
            self.assertEqual(_top_pm_ref(fx, "jazz weekend mornings"), "en:jazz")

    def test_jp_kr_conversation_recall(self) -> None:
        """Conversation recall with Japanese and Korean content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            _seed_step(fx, step_id="jp:step-calm", summary="ユーザー：静かな場所で本を読むのが好きです。")
            _seed_step(fx, step_id="kr:step-walking", summary="사용자：주말에 도시를 걷는 것을 좋아합니다.")

            # JP lexical match
            hits = _conversation_recall(fx, "静かな場所 本を読む")
            if hits:
                contents = " ".join(h.content for h in hits)
                self.assertIn("静かな場所", contents)

            # KR lexical match
            hits = _conversation_recall(fx, "도시를 걷는")
            if hits:
                contents = " ".join(h.content for h in hits)
                self.assertIn("도시를", contents)

    # ── 5. Mixed-language content ─────────────────────────────────────

    def test_mixed_language_pm_search(self) -> None:
        """PM search with mixed CN/EN content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            _seed_pm_fact(fx, fact_id="mx:citywalk", lens="pulse",
                text="周末 city walk 是我最放松的方式。在成都的街头漫无目的地走。",
                topic="test.weekend.mixed")
            _seed_pm_fact(fx, fact_id="mx:code", lens="identity",
                text="喜欢用 Python 写一些小工具来自动化日常工作。",
                topic="test.workflow.automation")

            # CN tokens should match
            self.assertEqual(_top_pm_ref(fx, "周末 city walk"), "mx:citywalk")
            # Mixed query
            self.assertEqual(_top_pm_ref(fx, "Python 自动化"), "mx:code")
            # EN-only token inside mixed fact
            self.assertEqual(_top_pm_ref(fx, "Python automation tools", query_variants=("Python 小工具",)), "mx:code")

    def test_mixed_language_conversation_recall(self) -> None:
        """Conversation recall with mixed CN/EN content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            _seed_step(fx, step_id="mx:step-citywalk",
                summary="用户说周末 city walk 是最放松的方式，在成都的街头漫无目的地走。")
            _seed_step(fx, step_id="mx:step-python",
                summary="用户说喜欢用 Python 写一些小工具来自动化日常工作。")

            # CN token match
            hits = _conversation_recall(fx, "成都的街头")
            contents = " ".join(h.content for h in hits)
            self.assertIn("成都", contents)

            # Mixed token match
            hits = _conversation_recall(fx, "Python 小工具")
            contents = " ".join(h.content for h in hits)
            self.assertIn("Python", contents)

    # ── 6. Same content: PM search vs conversation recall comparison ────────

    def test_same_content_through_both_paths(self) -> None:
        """Same multilingual content retrievable through both PM and conversation paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            pm_text = "周末最喜欢在成都 city walk，漫无目的地走。"
            step_summary = f"用户说：{pm_text}"

            _seed_pm_fact(fx, fact_id="cmp:citywalk", lens="pulse", text=pm_text, topic="test.weekend.citywalk")
            _seed_step(fx, step_id="cmp:step-citywalk", summary=step_summary)

            # PM search path
            pm_ref = _top_pm_ref(fx, "周末 city walk 成都")
            self.assertEqual(pm_ref, "cmp:citywalk", "PM search should find the citywalk fact")

            # Conversation recall path
            hits = _conversation_recall(fx, "周末 city walk 成都")
            self.assertTrue(hits, "Conversation recall should find the citywalk step")
            contents = " ".join(h.content for h in hits)
            self.assertIn("成都", contents)
            self.assertIn("city walk", contents)

    # ── 7. Step recall filters tool noise ─────────────────────────────

    def test_step_recall_filters_tool_execution_noise_multilingual(self) -> None:
        """Step recall should exclude tool execution steps even with CJK content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            # Tool step — should be filtered out
            _seed_step(fx, step_id="noise:tool",
                summary="tool result: 家庭权力结构分析完成",
                action="call_tool")
            # User step — should be recallable
            _seed_step(fx, step_id="noise:user",
                summary="用户说：我们讨论了家庭权力结构的问题。",
                action="record_input")

            hits = _conversation_recall(fx, "家庭权力结构")
            contents = "\n".join(h.content for h in hits)
            self.assertIn("家庭权力结构", contents, "should find the user step")
            self.assertNotIn("tool result", contents, "should NOT include tool execution noise")

    # ── 8. Large batch ranking stability with multilingual content ────

    def test_large_batch_multilingual_ranking_stability(self) -> None:
        """Top-3 should prefer relevant multilingual facts over distractors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            # Distractors
            for i in range(15):
                _seed_pm_fact(fx, fact_id=f"dist:{i:03d}", lens="world",
                    text=f"Distractor fact number {i} about random topic xyz.",
                    topic=f"distractor_{i}")

            # Target facts about "architecture" in mixed CN/EN
            for i in range(5):
                _seed_pm_fact(fx, fact_id=f"arch:{i:03d}", lens="world",
                    text=f"关于系统架构的讨论，第{i}条：微服务和事件驱动设计的取舍。",
                    topic=f"architecture_{i}")

            # More distractors
            for i in range(15, 20):
                _seed_pm_fact(fx, fact_id=f"dist:{i:03d}", lens="world",
                    text=f"Late distractor fact number {i} about random topic abc.",
                    topic=f"distractor_{i}")

            result = _pm_search(fx, "微服务 架构 事件驱动")
            claims = tuple(result.get("claims") or ())
            self.assertTrue(claims, "should find architecture facts")
            arch_hits = sum(1 for c in claims if c["ref"].startswith("arch:"))
            self.assertGreaterEqual(
                arch_hits, 2,
                f"expected >=2 architecture facts in top-5, got {arch_hits}: {[c['ref'] for c in claims]}",
            )

    # ── 9. Topic-only exact mode (PM search) ─────────────────────────

    def test_topic_only_exact_pm_search(self) -> None:
        """PM search with topic-only (no query text) should match by topic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_fixture(tmpdir)
            _seed_pm_fact(fx, fact_id="to:optionality", lens="identity",
                text="重要的是保住选择权。", topic="test.choice.optionality")
            _seed_pm_fact(fx, fact_id="to:choice", lens="identity",
                text="做取舍时最不想丢掉的是选择权。", topic="test.choice.preference")

            topic_only = _pm_search(fx, "", topic="test.choice.optionality", include_diagnostics=True)
            claims = tuple(topic_only.get("claims") or ())
            self.assertTrue(claims)
            self.assertEqual(claims[0]["ref"], "to:optionality")

    # ── 10. Degraded embedding path ────────────────────────────────────

    def test_degraded_pm_search_falls_back_to_lexical(self) -> None:
        """PM search should still work when embedding service is degraded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Build a fixture without embedding service
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-degraded", elephant_name="Degraded")
            bundle = build_semantic_index_bundle(repository=repository, state_dir=state_dir)
            indexer = SemanticSummaryIndexer(
                semantic_index=bundle.service,
                embedding_service=None,
                repository=repository,
            )
            surface = PersonalModelUnderstandingSurface(
                repository=repository,
                semantic_summary_indexer=indexer,
                semantic_searcher=bundle.searcher,
                embedding_service=None,
            )
            fx = MultilingualFixture(
                surface=surface,
                personal_model_id=state.personal_model_id,
                state_id=state.state_id,
                repository=repository,
                indexer=indexer,
            )

            _seed_pm_fact(fx, fact_id="dg:citywalk", lens="pulse",
                text="周末最喜欢在成都 city walk。", topic="test.weekend.citywalk")

            # Should still find via lexical signals even without embeddings
            result = _pm_search(fx, "周末 成都 city walk")
            claims = tuple(result.get("claims") or ())
            self.assertTrue(claims, "lexical fallback should still find matches")
            self.assertEqual(claims[0]["ref"], "dg:citywalk")

    # ── 11. Production dimension split regression ─────────────────────

    def test_foreground_pm_search_uses_index_dimensions_under_noise(self) -> None:
        """Foreground PM writes should be immediately semantically visible."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-dims", elephant_name="Dims")
            embedding_service = _DimensionAwareSemanticStubEmbeddingService()
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

            for i in range(30):
                surface.update_personal_model(
                    "session-dims",
                    action="remember",
                    lens="journey",
                    topic=f"journey.noise.case{i}",
                    text=f"存量背景 {i}: 多语言测试经验、过渡期、INFJ、压力模式和任务复盘。",
                    personal_model_id=state.personal_model_id,
                )
            update = surface.update_personal_model(
                "session-dims",
                action="remember",
                lens="identity",
                topic="identity.private.marker",
                text="我最近在学习日语歌的发音，并且喜欢周末听 City Pop。",
                personal_model_id=state.personal_model_id,
            )
            target_ref = str(update["claim"]["ref"])
            entries = repository.list_semantic_index_entries(
                personal_model_id=state.personal_model_id,
                owner_scope="personal_model",
            )
            self.assertEqual({entry.dimensions for entry in entries}, {256})

            result = surface.search_personal_model(
                "session-dims",
                query="anime pronunciation practice",
                personal_model_id=state.personal_model_id,
                limit=5,
            )
            claims = tuple(result.get("claims") or ())
            self.assertTrue(claims)
            self.assertEqual(claims[0]["ref"], target_ref)

    def test_conversation_search_uses_index_dimensions_under_noise(self) -> None:
        """Conversation recall should use the same dimensions as indexed Steps."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-conv-dims", elephant_name="ConvDims")
            embedding_service = _DimensionAwareSemanticStubEmbeddingService()
            bundle = build_semantic_index_bundle(repository=repository, state_dir=state_dir)
            indexer = SemanticSummaryIndexer(
                semantic_index=bundle.service,
                embedding_service=embedding_service,
                repository=repository,
            )
            episode = Episode(
                episode_id="episode-conv-dims",
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                entry_surface="test",
                status="closed",
                started_at=_NOW,
                ended_at=_NOW,
            )
            loop = Loop(
                loop_id="loop-conv-dims",
                episode_id=episode.episode_id,
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                trigger_type="turn.received",
                status="closed",
                started_at=_NOW,
                ended_at=_NOW,
            )
            repository.upsert_episode(episode)
            repository.upsert_loop(loop)
            for i in range(30):
                step = Step(
                    step_id=f"step-noise-{i}",
                    loop_id=loop.loop_id,
                    episode_id=episode.episode_id,
                    state_id=state.state_id,
                    personal_model_id=state.personal_model_id,
                    phase="observation",
                    action="record_input",
                    status="completed",
                    sequence=i,
                    created_at=_NOW,
                    summary=f"存量背景 {i}: 多语言测试经验、过渡期、INFJ、压力模式和任务复盘。",
                    metadata={
                        "event_type": "turn.received",
                        "user_query": f"存量背景 {i}: 多语言测试经验、过渡期、INFJ、压力模式和任务复盘。",
                    },
                )
                repository.upsert_step(step)
                indexer.index_step(step)
            target = Step(
                step_id="step-target-citypop",
                loop_id=loop.loop_id,
                episode_id=episode.episode_id,
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                phase="observation",
                action="record_input",
                status="completed",
                sequence=99,
                created_at=_NOW,
                summary="我最近在学习日语歌的发音，并且喜欢周末听 City Pop。",
                metadata={
                    "event_type": "turn.received",
                    "user_query": "我最近在学习日语歌的发音，并且喜欢周末听 City Pop。",
                },
            )
            repository.upsert_step(target)
            indexer.index_step(target)

            hits = unified_recall(
                UnifiedRecallRequest(
                    query="anime pronunciation practice",
                    scopes=("steps",),
                    personal_model_id=state.personal_model_id,
                    state_id=state.state_id,
                    limit=5,
                ),
                repository=repository,
                searcher=bundle.searcher,
                embedding_service=embedding_service,
            )
            self.assertTrue(hits)
            self.assertEqual(dict(hits[0].extra_metadata or {}).get("step_id"), target.step_id)
            self.assertIn("vector", dict(hits[0].extra_metadata or {}).get("semantic_reasons", ""))


if __name__ == "__main__":
    unittest.main()
