"""End-to-end wiring test: close an episode → SemanticSummaryIndexer writes
the exit_summary into the semantic index → HybridSemanticSearcher recovers it.

This catches the "producer/consumer index path mismatch" regression: if
either side uses a different SQLite file (tempdir vs durable state dir), the
test fails at the search step.
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

from packages.contracts import Episode
from packages.embeddings import EmbeddingVector
from packages.evidence import (
    SemanticSummaryIndexer,
    build_semantic_index_bundle,
)
from packages.semantic_index import (
    HybridSemanticSearcher,
    SemanticSearchQuery,
)
from packages.storage import RuntimeStorageRepository


_NOW = datetime(2026, 4, 30, 10, 0, tzinfo=timezone.utc)


class _StubEmbeddingService:
    """Deterministic embedding: letters map to one-hot buckets."""

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

    def embed_text(self, text: str, *, request_id: str = "", task: str = "", latency_mode: str = "") -> EmbeddingVector:
        del request_id, task, latency_mode
        bucket = [0.0] * self._dimensions
        lowered = text.lower()
        for ch in lowered:
            if ch.isalpha():
                idx = (ord(ch) - ord("a")) % self._dimensions
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


class EpisodeCloseSemanticIndexWritebackTest(unittest.TestCase):
    def test_episode_exit_summary_is_indexed_and_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)

            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()

            state = repository.create_state(elephant_id="elephant-aa", elephant_name="AA")

            bundle = build_semantic_index_bundle(
                repository=repository,
                state_dir=state_dir,
            )
            indexer = SemanticSummaryIndexer(
                semantic_index=bundle.service,
                embedding_service=_StubEmbeddingService(),
                repository=repository,
            )

            closed_episode = Episode(
                episode_id="episode-prior",
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                entry_surface="cli",
                status="closed",
                started_at=_NOW,
                ended_at=_NOW,
                exit_summary="User chose Redis caching over memcached for the aegis project.",
                metadata={"topic": "caching strategy"},
            )
            # Simulate the `close_episode_lifecycle` hook path.
            result = indexer.index_episode_exit(closed_episode)
            self.assertIsNotNone(result, "indexer must return a success handle on happy path")

            searcher = HybridSemanticSearcher(
                repository=repository,
                backend=bundle.backend,
            )
            matches = searcher.search(
                SemanticSearchQuery(
                    text="redis caching",
                    owner_scope="episode",
                    limit=3,
                )
            )

        self.assertTrue(
            matches,
            "hybrid search must return at least one match for the indexed exit_summary",
        )
        source_ids = {m.semantic_index_entry.source_id for m in matches}
        self.assertIn(
            f"episode:{closed_episode.episode_id}",
            source_ids,
            "indexed exit_summary should surface under source_id 'episode:<id>'",
        )

    def test_indexer_noop_when_episode_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)

            repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
            repository.bootstrap()
            bundle = build_semantic_index_bundle(repository=repository, state_dir=state_dir)
            indexer = SemanticSummaryIndexer(
                semantic_index=bundle.service,
                embedding_service=_StubEmbeddingService(),
                repository=repository,
            )
            self.assertIsNone(indexer.index_episode_exit(None))


if __name__ == "__main__":
    unittest.main()
