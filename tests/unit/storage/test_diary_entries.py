from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from packages.contracts import DiaryEntry, SemanticIndexEntry
from packages.storage import RuntimeStorageRepository


class DiaryEntryStorageTest(unittest.TestCase):
    def test_delete_diary_entry_removes_one_personal_model_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            repository.ensure_default_personal_model(personal_model_id="you")
            repository.ensure_default_personal_model(personal_model_id="other", display_name="Other")
            repository.upsert_diary_entry(
                DiaryEntry(
                    entry_id="diary:one",
                    personal_model_id="you",
                    entry_date="2026-05-14",
                    content="today",
                    generated_at=datetime.now(timezone.utc),
                )
            )
            repository.upsert_diary_entry(
                DiaryEntry(
                    entry_id="diary:other",
                    personal_model_id="other",
                    entry_date="2026-05-14",
                    content="other",
                    generated_at=datetime.now(timezone.utc),
                )
            )

            deleted = repository.delete_diary_entry(personal_model_id="you", entry_date="2026-05-14")

            self.assertTrue(deleted)
            self.assertIsNone(repository.load_diary_entry(personal_model_id="you", entry_date="2026-05-14"))
            self.assertIsNotNone(repository.load_diary_entry(personal_model_id="other", entry_date="2026-05-14"))
            self.assertFalse(repository.delete_diary_entry(personal_model_id="you", entry_date="2026-05-14"))

    def test_delete_diary_entry_marks_semantic_index_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            repository.ensure_default_personal_model(personal_model_id="you")
            repository.ensure_default_personal_model(personal_model_id="other", display_name="Other")
            repository.upsert_diary_entry(
                DiaryEntry(
                    entry_id="diary:one",
                    personal_model_id="you",
                    entry_date="2026-05-14",
                    content="today",
                    generated_at=datetime.now(timezone.utc),
                )
            )
            repository.upsert_semantic_index_entry(
                SemanticIndexEntry(
                    semantic_index_entry_id="semantic:diary:one",
                    owner_scope="personal_model",
                    source_id="diary:you:2026-05-14",
                    provider_id="stub-provider",
                    model_id="stub-model",
                    dimensions=4,
                    content_hash="sha256:diary-one",
                    personal_model_id="you",
                    created_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
                )
            )
            repository.upsert_semantic_index_entry(
                SemanticIndexEntry(
                    semantic_index_entry_id="semantic:diary:other",
                    owner_scope="personal_model",
                    source_id="diary:other:2026-05-14",
                    provider_id="stub-provider",
                    model_id="stub-model",
                    dimensions=4,
                    content_hash="sha256:diary-other",
                    personal_model_id="other",
                    created_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
                )
            )

            deleted = repository.delete_diary_entry(personal_model_id="you", entry_date="2026-05-14")
            deleted_index = repository.load_semantic_index_entry("semantic:diary:one")
            other_index = repository.load_semantic_index_entry("semantic:diary:other")

            self.assertTrue(deleted)
            self.assertIsNotNone(deleted_index)
            assert deleted_index is not None
            self.assertEqual(deleted_index.status, "deleted")
            self.assertEqual(deleted_index.metadata["deleted_by"], "diary_delete")
            self.assertEqual(deleted_index.metadata["retention_lifecycle_status"], "deleted")
            self.assertIsNotNone(other_index)
            assert other_index is not None
            self.assertEqual(other_index.status, "indexed")


if __name__ == "__main__":
    unittest.main()
