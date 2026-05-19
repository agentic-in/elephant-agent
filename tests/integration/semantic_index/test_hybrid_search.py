from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.semantic_index import (
    HybridSemanticSearcher,
    SQLiteVecSemanticIndex,
    SemanticIndexHealth,
    SemanticIndexDocument,
    SemanticIndexService,
    SemanticIndexWriteResult,
    SemanticSearchQuery,
)
from packages.storage import RuntimeStorageRepository


class HybridSemanticSearchTest(unittest.TestCase):
    def test_hybrid_search_uses_scope_gates_and_weighted_rrf(self) -> None:
        now = datetime(2026, 4, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repository = RuntimeStorageRepository(root / "state" / "elephant.sqlite3")
            repository.bootstrap()
            alpha = repository.create_state(elephant_id="elephant-alpha", elephant_name="Alpha")
            beta = repository.create_state(elephant_id="elephant-beta", elephant_name="Beta")
            backend = SQLiteVecSemanticIndex(root / "semantic.sqlite3")
            service = SemanticIndexService(repository=repository, backend=backend)

            self._index(
                service,
                source_id="step:alpha-error",
                state_id=alpha.state_id,
                personal_model_id=alpha.personal_model_id,
                text="ERR_PACKAGE_VERIFY failed while checking dashboard assets.",
                vector=(0.0, 1.0, 0.0, 0.0),
                created_at=now,
            )
            self._index(
                service,
                source_id="step:alpha-vector",
                state_id=alpha.state_id,
                personal_model_id=alpha.personal_model_id,
                text="Lunch notes unrelated to release verification.",
                vector=(1.0, 0.0, 0.0, 0.0),
                created_at=now,
            )
            self._index(
                service,
                source_id="step:beta-error",
                state_id=beta.state_id,
                personal_model_id=beta.personal_model_id,
                text="ERR_PACKAGE_VERIFY belongs to another elephant.",
                vector=(1.0, 0.0, 0.0, 0.0),
                created_at=now,
            )
            searcher = HybridSemanticSearcher(repository=repository, backend=backend)

            matches = searcher.search(
                SemanticSearchQuery(
                    text="ERR_PACKAGE_VERIFY",
                    vector=(1.0, 0.0, 0.0, 0.0),
                    dimensions=4,
                    owner_scope="state",
                    state_id=alpha.state_id,
                    limit=3,
                )
            )

        self.assertEqual(
            tuple(match.document.source_id for match in matches),
            ("step:alpha-error", "step:alpha-vector"),
        )
        self.assertIn("keyword_exact", matches[0].signal_scores)
        self.assertIn("vector", matches[0].signal_scores)
        self.assertIn("vector", matches[1].signal_scores)
        self.assertGreater(matches[0].score, matches[1].score)
        self.assertNotIn("step:beta-error", {match.document.source_id for match in matches})

    def test_degraded_vector_search_falls_back_to_lexical_signals(self) -> None:
        now = datetime(2026, 4, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repository = RuntimeStorageRepository(root / "state" / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-alpha", elephant_name="Alpha")
            backend = _DegradedVectorBackend()
            service = SemanticIndexService(repository=repository, backend=backend)

            self._index(
                service,
                source_id="step:heartbeat",
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                text="Dashboard heartbeat panel records latency spikes and telemetry drift.",
                vector=(0.0, 1.0, 0.0, 0.0),
                created_at=now,
            )
            self._index(
                service,
                source_id="step:release",
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                text="Release checklist tracks package verification and certification gates.",
                vector=(1.0, 0.0, 0.0, 0.0),
                created_at=now,
            )
            searcher = HybridSemanticSearcher(repository=repository, backend=backend)

            matches = searcher.search(
                SemanticSearchQuery(
                    text="dashboard heartbeat telemetry",
                    vector=(1.0, 0.0, 0.0, 0.0),
                    dimensions=4,
                    owner_scope="state",
                    state_id=state.state_id,
                    limit=1,
                )
            )

        self.assertEqual(tuple(match.document.source_id for match in matches), ("step:heartbeat",))
        self.assertEqual(backend.search_calls, 0)
        self.assertEqual(
            set(matches[0].signal_scores),
            {"token_coverage", "keyword_exact", "bm25", "ngram"},
        )
        self.assertNotIn("vector", matches[0].signal_scores)

    def test_unicode_lexical_matches_cjk_split_and_fuzzy_queries(self) -> None:
        now = datetime(2026, 4, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repository = RuntimeStorageRepository(root / "state" / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-alpha", elephant_name="Alpha")
            backend = _DegradedVectorBackend()
            service = SemanticIndexService(repository=repository, backend=backend)
            self._index(
                service,
                source_id="step:fog-crossing",
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                text="我喜欢像站在起雾的路口那样慢慢做决定。",
                vector=(1.0, 0.0, 0.0, 0.0),
                created_at=now,
            )
            self._index(
                service,
                source_id="step:quiet-corner",
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                text="能量低的时候，我需要一个安静角落。",
                vector=(0.0, 1.0, 0.0, 0.0),
                created_at=now,
            )
            searcher = HybridSemanticSearcher(repository=repository, backend=backend)

            split_matches = searcher.search(
                SemanticSearchQuery(
                    text="起雾 路口",
                    owner_scope="state",
                    state_id=state.state_id,
                    limit=1,
                )
            )
            fuzzy_matches = searcher.search(
                SemanticSearchQuery(
                    text="安净角落",
                    owner_scope="state",
                    state_id=state.state_id,
                    limit=1,
                )
            )

        self.assertEqual(
            tuple(match.document.source_id for match in split_matches),
            ("step:fog-crossing",),
        )
        self.assertEqual(
            tuple(match.document.source_id for match in fuzzy_matches),
            ("step:quiet-corner",),
        )
        self.assertTrue({"token_coverage", "ngram"} & set(split_matches[0].signal_scores))
        self.assertIn("ngram", fuzzy_matches[0].signal_scores)

    def _index(
        self,
        service: SemanticIndexService,
        *,
        source_id: str,
        state_id: str,
        personal_model_id: str,
        text: str,
        vector: tuple[float, ...],
        created_at: datetime,
    ) -> None:
        service.index_document(
            SemanticIndexDocument(
                source_id=source_id,
                owner_scope="state",
                text=text,
                vector=vector,
                provider_id="provider-local",
                model_id="elephant-embed",
                dimensions=4,
                personal_model_id=personal_model_id,
                state_id=state_id,
                metadata={"indexed_text": text, "created_at": created_at.isoformat()},
            )
        )


class _DegradedVectorBackend:
    def __init__(self) -> None:
        self.search_calls = 0

    def health(self) -> SemanticIndexHealth:
        return SemanticIndexHealth(
            status="degraded",
            summary="sqlite-vec unavailable; lexical degraded path remains available.",
            vector_available=False,
            lexical_available=True,
        )

    def upsert(self, vector) -> SemanticIndexWriteResult:
        del vector
        return SemanticIndexWriteResult(
            status="degraded",
            accepted=0,
            summary="semantic vector write skipped because sqlite-vec is unavailable.",
        )

    def search(self, query):
        del query
        self.search_calls += 1
        raise AssertionError("vector search should not run while vector health is degraded")

    def delete(self, request) -> SemanticIndexWriteResult:
        del request
        return SemanticIndexWriteResult(status="degraded", accepted=0, summary="semantic vector delete skipped.")

    def rebuild_plan(self, *, current, desired):
        del current, desired
        raise AssertionError("rebuild planning is not used by lexical degraded search")


if __name__ == "__main__":
    unittest.main()
