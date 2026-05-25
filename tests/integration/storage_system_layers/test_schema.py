from __future__ import annotations
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.storage import RuntimeStorageRepository
from packages.storage.repository_bootstrap_methods import LEGACY_STORAGE_TABLES
from packages.storage.repository_support import SCHEMA_PATH, SCHEMA_VERSION


class StorageSystemLayerSchemaTest(unittest.TestCase):
    def test_bootstrap_installs_clean_terminal_schema_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "state" / "elephant.sqlite3"
            repository = RuntimeStorageRepository(database_path)

            bootstrap = repository.bootstrap()

            self.assertEqual(bootstrap.schema_version, SCHEMA_VERSION)
            self.assertEqual(repository.schema_version(), SCHEMA_VERSION)
            self.assertEqual(SCHEMA_VERSION, 1)
            self.assertEqual(SCHEMA_PATH.name, "schema.sql")

            with sqlite3.connect(database_path) as connection:
                table_names = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                state_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(states)").fetchall()
                }
                episode_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(episodes)").fetchall()
                }
                job_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(learning_jobs)").fetchall()
                }
                fact_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(personal_model_facts)").fetchall()
                }
                semantic_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(semantic_index_entries)").fetchall()
                }
                index_names = {
                    str(row[1])
                    for row in connection.execute("PRAGMA index_list(states)").fetchall()
                } | {
                    str(row[1])
                    for row in connection.execute("PRAGMA index_list(episodes)").fetchall()
                } | {
                    str(row[1])
                    for row in connection.execute("PRAGMA index_list(loops)").fetchall()
                } | {
                    str(row[1])
                    for row in connection.execute("PRAGMA index_list(steps)").fetchall()
                }

        self.assertTrue(
            {
                "storage_metadata",
                "personal_models",
                "states",
                "episodes",
                "loops",
                "steps",
                "semantic_index_entries",
                "learning_jobs",
                "personal_model_facts",
                "personal_model_open_questions",
                "diary_entries",
                "personal_model_growth",
                "canonical_elephant_identities",
                "local_agent_runtimes",
            }.issubset(table_names)
        )
        self.assertIn("current_context_note", state_columns)
        self.assertIn("elephant_identity_text", state_columns)
        self.assertIn("updated_at", episode_columns)
        self.assertIn("interruption_state", episode_columns)
        self.assertIn("result_json", job_columns)
        self.assertIn("last_accessed_at", fact_columns)
        self.assertIn("source_id", semantic_columns)
        self.assertIn("idx_states_anchor_status", index_names)
        self.assertIn("idx_episodes_elephant_started", index_names)
        self.assertIn("idx_episodes_personal_model_status_started", index_names)
        self.assertIn("idx_episodes_state_status_started", index_names)
        self.assertIn("idx_loops_episode_started", index_names)
        self.assertIn("idx_loops_checkpoint_scan", index_names)
        self.assertIn("idx_steps_state_pm_created", index_names)
        self.assertFalse(LEGACY_STORAGE_TABLES.intersection(table_names))

    def test_bootstrap_is_idempotent_for_clean_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "state" / "elephant.sqlite3"
            repository = RuntimeStorageRepository(database_path)

            first = repository.bootstrap()
            second = repository.bootstrap()

        self.assertEqual(first.schema_version, SCHEMA_VERSION)
        self.assertEqual(second.schema_version, SCHEMA_VERSION)

    def test_bootstrap_backfills_runtime_indexes_for_existing_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "state" / "elephant.sqlite3"
            repository = RuntimeStorageRepository(database_path)
            repository.bootstrap()

            with sqlite3.connect(database_path) as connection:
                connection.execute("DROP INDEX idx_states_anchor_status")
                connection.execute("DROP INDEX idx_episodes_state_status_started")
                connection.execute("DROP INDEX idx_episodes_elephant_started")
                connection.execute("DROP INDEX idx_loops_episode_started")
                connection.execute("DROP INDEX idx_loops_checkpoint_scan")
                connection.commit()

            repository.bootstrap()

            with sqlite3.connect(database_path) as connection:
                index_names = {
                    str(row[1])
                    for row in connection.execute("PRAGMA index_list(states)").fetchall()
                } | {
                    str(row[1])
                    for row in connection.execute("PRAGMA index_list(episodes)").fetchall()
                } | {
                    str(row[1])
                    for row in connection.execute("PRAGMA index_list(loops)").fetchall()
                }

        self.assertIn("idx_states_anchor_status", index_names)
        self.assertIn("idx_episodes_state_status_started", index_names)
        self.assertIn("idx_episodes_elephant_started", index_names)
        self.assertIn("idx_loops_episode_started", index_names)
        self.assertIn("idx_loops_checkpoint_scan", index_names)

    def test_repository_connections_enable_wal_busy_timeout_and_foreign_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "state" / "elephant.sqlite3"
            repository = RuntimeStorageRepository(database_path)
            repository.bootstrap()

            with repository.connection() as connection:
                foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
                journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                busy_timeout = int(connection.execute("PRAGMA busy_timeout").fetchone()[0])

        self.assertEqual(foreign_keys, 1)
        self.assertEqual(journal_mode, "wal")
        self.assertGreaterEqual(busy_timeout, 5000)

    def test_schema_declares_reset_delete_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "state" / "elephant.sqlite3"
            repository = RuntimeStorageRepository(database_path)
            repository.bootstrap()

            with sqlite3.connect(database_path) as connection:
                state_fks = _foreign_keys(connection, "states")
                episode_fks = _foreign_keys(connection, "episodes")
                semantic_fks = _foreign_keys(connection, "semantic_index_entries")

        self.assertEqual(state_fks["personal_models"], "CASCADE")
        self.assertEqual(episode_fks["states"], "CASCADE")
        self.assertEqual(semantic_fks["states"], "CASCADE")
        self.assertNotIn("records", semantic_fks)

    def test_bootstrap_rejects_existing_database_without_clean_schema_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "state" / "elephant.sqlite3"
            database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(database_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    );
                    INSERT INTO schema_migrations(version, applied_at)
                    VALUES (16, '2026-05-14T00:00:00+00:00');
                    CREATE TABLE states (
                        state_id TEXT PRIMARY KEY,
                        authored_identity TEXT NOT NULL DEFAULT ''
                    );
                    """
                )

            repository = RuntimeStorageRepository(database_path)
            with self.assertRaisesRegex(RuntimeError, "no clean schema marker"):
                repository.bootstrap()

            self.assertEqual(repository.schema_version(), 0)

    def test_bootstrap_resets_same_version_schema_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "state" / "elephant.sqlite3"
            database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(database_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE storage_metadata (
                        metadata_key TEXT PRIMARY KEY,
                        metadata_value TEXT NOT NULL
                    );
                    INSERT INTO storage_metadata(metadata_key, metadata_value)
                    VALUES ('schema_version', '1');
                    CREATE TABLE semantic_index_entries (
                        semantic_index_entry_id TEXT PRIMARY KEY,
                        source_record_id TEXT NOT NULL
                    );
                    INSERT INTO semantic_index_entries(semantic_index_entry_id, source_record_id)
                    VALUES ('old-entry', 'old-source');
                    """
                )

            repository = RuntimeStorageRepository(database_path)
            repository.bootstrap()

            with sqlite3.connect(database_path) as connection:
                semantic_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(semantic_index_entries)").fetchall()
                }
                rows = connection.execute("SELECT semantic_index_entry_id FROM semantic_index_entries").fetchall()

        self.assertIn("source_id", semantic_columns)
        self.assertNotIn("source_record_id", semantic_columns)
        self.assertEqual(rows, [])


def _foreign_keys(connection: sqlite3.Connection, table_name: str) -> dict[str, str]:
    rows = connection.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
    return {str(row[2]): str(row[6]).upper() for row in rows}


if __name__ == "__main__":
    unittest.main()
