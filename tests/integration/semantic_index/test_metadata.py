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
    SemanticIndexDocument,
    SemanticIndexService,
    SemanticIndexVectorQuery,
    SemanticIndexWriteResult,
    semantic_content_hash,
)
from packages.storage import RuntimeStorageRepository


class SemanticIndexMetadataTest(unittest.TestCase):
    def test_service_persists_vector_metadata_and_indexes_vector(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repository = RuntimeStorageRepository(root / "state" / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-alpha", elephant_name="Alpha")
            backend = SQLiteVecSemanticIndex(root / "semantic.sqlite3")
            service = SemanticIndexService(repository=repository, backend=backend)

            entry = service.index_document(
                SemanticIndexDocument(
                    source_id="step:alpha",
                    owner_scope="state",
                    text="release checklist and package verification",
                    vector=(1.0, 0.0, 0.0, 0.0),
                    provider_id="provider-local",
                    model_id="elephant-embed",
                    dimensions=4,
                    personal_model_id=state.personal_model_id,
                    state_id=state.state_id,
                )
            )
            loaded = repository.load_semantic_index_entry(entry.semantic_index_entry_id)
            matches = backend.search(SemanticIndexVectorQuery(4, (1.0, 0.0, 0.0, 0.0), limit=1))

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.source_id, "step:alpha")
        self.assertEqual(loaded.provider_id, "provider-local")
        self.assertEqual(loaded.model_id, "elephant-embed")
        self.assertEqual(loaded.dimensions, 4)
        self.assertEqual(loaded.owner_scope, "state")
        self.assertEqual(
            loaded.content_hash,
            semantic_content_hash("release checklist and package verification"),
        )
        self.assertEqual(loaded.status, "indexed")
        self.assertTrue(loaded.vector_ref.startswith("sqlite-vec:4:semantic-index:"))
        self.assertEqual(loaded.metadata["backend_version"], "0.1.9")
        self.assertEqual(matches[0].semantic_index_entry_id, loaded.semantic_index_entry_id)

    def test_service_keeps_metadata_when_vector_backend_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-alpha", elephant_name="Alpha")
            service = SemanticIndexService(repository=repository, backend=_DegradedBackend())

            entry = service.index_document(
                SemanticIndexDocument(
                    source_id="step:alpha",
                    owner_scope="state",
                    text="degraded vector write",
                    vector=(0.0, 1.0, 0.0, 0.0),
                    provider_id="provider-local",
                    model_id="elephant-embed",
                    dimensions=4,
                    personal_model_id=state.personal_model_id,
                    state_id=state.state_id,
                )
            )
            loaded = repository.load_semantic_index_entry(entry.semantic_index_entry_id)

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.status, "pending_vector")
        self.assertEqual(loaded.vector_ref, "")
        self.assertEqual(loaded.metadata["vector_status"], "degraded")
        self.assertEqual(loaded.content_hash, semantic_content_hash("degraded vector write"))

    def test_service_deletes_metadata_and_vectors_by_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repository = RuntimeStorageRepository(root / "state" / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-alpha", elephant_name="Alpha")
            backend = SQLiteVecSemanticIndex(root / "semantic.sqlite3")
            service = SemanticIndexService(repository=repository, backend=backend)
            entry = service.index_document(
                SemanticIndexDocument(
                    source_id="step:alpha",
                    owner_scope="state",
                    text="delete scoped semantic vector",
                    vector=(0.0, 0.0, 1.0, 0.0),
                    provider_id="provider-local",
                    model_id="elephant-embed",
                    dimensions=4,
                    personal_model_id=state.personal_model_id,
                    state_id=state.state_id,
                )
            )

            result = service.delete_scope(state_id=state.state_id)
            loaded = repository.load_semantic_index_entry(entry.semantic_index_entry_id)
            matches = backend.search(SemanticIndexVectorQuery(4, (0.0, 0.0, 1.0, 0.0), limit=1))

        self.assertEqual(result.metadata_deleted, 1)
        self.assertEqual(result.vector_deleted, 1)
        self.assertIsNone(loaded)
        self.assertEqual(matches, ())

    def test_rebuild_plan_tracks_provider_model_dimension_and_content_changes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repository = RuntimeStorageRepository(root / "state" / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-alpha", elephant_name="Alpha")
            service = SemanticIndexService(
                repository=repository,
                backend=SQLiteVecSemanticIndex(root / "semantic.sqlite3"),
            )
            original = SemanticIndexDocument(
                source_id="step:alpha",
                owner_scope="state",
                text="stable semantic document",
                vector=(1.0, 0.0, 0.0, 0.0),
                provider_id="provider-local",
                model_id="elephant-embed",
                dimensions=4,
                personal_model_id=state.personal_model_id,
                state_id=state.state_id,
            )
            service.index_document(original)

            reuse = service.rebuild_plan(
                desired_documents=(original,),
                owner_scope="state",
                state_id=state.state_id,
            )
            changed_dimensions = SemanticIndexDocument(
                source_id="step:alpha",
                owner_scope="state",
                text="stable semantic document",
                vector=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                provider_id="provider-local",
                model_id="elephant-embed",
                dimensions=8,
                personal_model_id=state.personal_model_id,
                state_id=state.state_id,
            )
            rebuild = service.rebuild_plan(
                desired_documents=(changed_dimensions,),
                owner_scope="state",
                state_id=state.state_id,
            )

        self.assertEqual(len(reuse.reuse_entry_ids), 1)
        self.assertEqual(reuse.rebuild_entry_ids, ())
        self.assertEqual(reuse.delete_entry_ids, ())
        self.assertEqual(len(rebuild.rebuild_entry_ids), 1)
        self.assertEqual(len(rebuild.delete_entry_ids), 1)
        self.assertEqual(rebuild.rebuild_documents, (changed_dimensions,))


class _DegradedBackend:
    backend_id = "sqlite-vec"

    def upsert(self, _vector) -> SemanticIndexWriteResult:
        return SemanticIndexWriteResult(
            status="degraded",
            accepted=0,
            summary="sqlite-vec unavailable",
            metadata={"reason": "test"},
        )


if __name__ == "__main__":
    unittest.main()
