from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.semantic_index import (
    SQLiteVecSemanticIndex,
    SemanticIndexDeleteRequest,
    SemanticIndexVector,
    SemanticIndexVectorQuery,
    sqlite_vec_runtime_state,
)


class SQLiteVecSemanticIndexTest(unittest.TestCase):
    def test_backend_health_reports_sqlite_vec_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = SQLiteVecSemanticIndex(Path(tmpdir) / "semantic.sqlite3")

            health = backend.health()

        self.assertEqual(health.status, "ready")
        self.assertTrue(health.vector_available)
        self.assertTrue(health.lexical_available)

    def test_backend_indexes_searches_restarts_and_deletes_vectors(self) -> None:
        self._skip_if_sqlite_vec_unavailable()
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "semantic.sqlite3"
            backend = SQLiteVecSemanticIndex(database_path)
            backend.upsert(SemanticIndexVector("entry-alpha", 4, (1.0, 0.0, 0.0, 0.0)))
            backend.upsert(SemanticIndexVector("entry-beta", 4, (0.0, 1.0, 0.0, 0.0)))

            restarted = SQLiteVecSemanticIndex(database_path)
            matches = restarted.search(SemanticIndexVectorQuery(4, (1.0, 0.0, 0.0, 0.0), limit=2))
            deleted = restarted.delete(SemanticIndexDeleteRequest(("entry-alpha",), dimensions=4))
            remaining = restarted.search(SemanticIndexVectorQuery(4, (1.0, 0.0, 0.0, 0.0), limit=2))

        self.assertEqual(
            tuple(match.semantic_index_entry_id for match in matches),
            ("entry-alpha", "entry-beta"),
        )
        self.assertEqual(matches[0].distance, 0.0)
        self.assertEqual(deleted.accepted, 1)
        self.assertEqual(tuple(match.semantic_index_entry_id for match in remaining), ("entry-beta",))

    def test_rebuild_plan_compares_vector_payloads_deterministically(self) -> None:
        backend = SQLiteVecSemanticIndex(Path("/tmp/elephant-unused.sqlite3"))
        current = (
            SemanticIndexVector("entry-keep", 4, (1.0, 0.0, 0.0, 0.0)),
            SemanticIndexVector("entry-delete", 4, (0.0, 1.0, 0.0, 0.0)),
            SemanticIndexVector("entry-rebuild", 4, (0.0, 0.0, 1.0, 0.0)),
        )
        desired = (
            SemanticIndexVector("entry-keep", 4, (1.0, 0.0, 0.0, 0.0)),
            SemanticIndexVector("entry-rebuild", 4, (0.0, 0.0, 0.0, 1.0)),
            SemanticIndexVector("entry-new", 4, (0.0, 0.0, 1.0, 0.0)),
        )

        plan = backend.rebuild_plan(current=current, desired=desired)

        self.assertEqual(plan.reuse_entry_ids, ("entry-keep",))
        self.assertEqual(plan.rebuild_entry_ids, ("entry-new", "entry-rebuild"))
        self.assertEqual(plan.delete_entry_ids, ("entry-delete",))

    def _skip_if_sqlite_vec_unavailable(self) -> None:
        if not sqlite_vec_runtime_state().ready:
            self.skipTest("sqlite-vec extension is unavailable in this Python environment")


if __name__ == "__main__":
    unittest.main()
