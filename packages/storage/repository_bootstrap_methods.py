"""SQLite bootstrap methods for the reset storage repository."""

from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from typing import Iterator

from .repository_support import SCHEMA_PATH, SCHEMA_VERSION, StorageBootstrapState

LEGACY_STORAGE_TABLES = frozenset(
    {
        "schema_migrations",
        "records",
        "groundings",
        "grounding_sources",
        "memory_entries",
        "memory_entry_groundings",
        "reflection_proposals",
        "reflection_proposal_groundings",
        "personal_model_observations",
        "embedding_provider_configs",
        "canonical_user_cards",
        "canonical_relationship_memories",
    }
)


def bootstrap(self) -> StorageBootstrapState:
    self.database_path.parent.mkdir(parents=True, exist_ok=True)
    with self.connection() as connection:
        version = self.schema_version(connection)
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema version {version} is newer than supported "
                f"schema version {SCHEMA_VERSION}"
            )
        if version == 0:
            _drop_legacy_storage_tables(connection)
            _require_empty_database(connection)
            _install_clean_schema(connection)
            _ensure_runtime_indexes(connection)
            _validate_clean_schema(connection)
            connection.commit()
        elif version == SCHEMA_VERSION:
            _drop_legacy_storage_tables(connection)
            try:
                _validate_clean_schema(connection)
            except RuntimeError:
                _reset_storage_schema(connection)
                _validate_clean_schema(connection)
            _ensure_runtime_indexes(connection)
            connection.commit()
        elif version == 1 and SCHEMA_VERSION == 2:
            _drop_legacy_storage_tables(connection)
            try:
                _validate_clean_schema(connection, require_path_tables=False)
                _migrate_schema_1_to_2(connection)
                _validate_clean_schema(connection)
            except RuntimeError:
                _reset_storage_schema(connection)
                _validate_clean_schema(connection)
            _ensure_runtime_indexes(connection)
            connection.commit()
        else:
            raise RuntimeError(
                f"database schema version {version} is older than clean schema "
                f"version {SCHEMA_VERSION}; reset runtime storage before bootstrapping"
            )
    return StorageBootstrapState(
        database_path=str(self.database_path),
        schema_version=SCHEMA_VERSION,
    )


def _require_empty_database(connection: sqlite3.Connection) -> None:
    existing_tables = _table_names(connection)
    if existing_tables:
        raise RuntimeError(
            "existing storage database has no clean schema marker; reset runtime "
            "storage before bootstrapping"
        )


def _write_schema_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO storage_metadata(metadata_key, metadata_value) VALUES(?, ?)",
        ("schema_version", str(version)),
    )


def _install_clean_schema(connection: sqlite3.Connection) -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema_sql)
    _write_schema_version(connection, SCHEMA_VERSION)


def _reset_storage_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    for table_name in sorted(_table_names(connection)):
        connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    connection.execute("PRAGMA foreign_keys = ON")
    _install_clean_schema(connection)


def _ensure_runtime_indexes(connection: sqlite3.Connection) -> None:
    """Idempotently backfill performance indexes for existing v1 databases."""

    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_states_anchor_status ON states(state_anchor, status)",
        "CREATE INDEX IF NOT EXISTS idx_episodes_state_started ON episodes(state_id, started_at)",
        (
            "CREATE INDEX IF NOT EXISTS idx_episodes_state_status_started "
            "ON episodes(state_id, status, started_at)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_episodes_personal_model_status_started "
            "ON episodes(personal_model_id, status, started_at)"
        ),
        "CREATE INDEX IF NOT EXISTS idx_episodes_elephant_started ON episodes(elephant_id, started_at)",
        "CREATE INDEX IF NOT EXISTS idx_loops_episode_started ON loops(episode_id, started_at)",
        (
            "CREATE INDEX IF NOT EXISTS idx_loops_checkpoint_scan "
            "ON loops(trigger_type, status, state_id, personal_model_id, started_at)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_steps_state_pm_created "
            "ON steps(state_id, personal_model_id, created_at)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_paths_pm_status_updated "
            "ON paths(personal_model_id, status, updated_at DESC)"
        ),
        "CREATE INDEX IF NOT EXISTS idx_paths_owner_updated ON paths(owner_elephant_id, updated_at DESC)",
        (
            "CREATE INDEX IF NOT EXISTS idx_path_steps_path_status_order "
            "ON path_steps(path_id, status, order_index, updated_at DESC)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_path_steps_pm_status_updated "
            "ON path_steps(personal_model_id, status, updated_at DESC)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_path_steps_assignee_status_updated "
            "ON path_steps(assignee_elephant_id, status, updated_at DESC)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_learning_summaries_step_created "
            "ON learning_summaries(path_step_id, created_at DESC)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_learning_summaries_path_created "
            "ON learning_summaries(path_id, created_at DESC)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_understanding_checks_step_updated "
            "ON understanding_checks(path_step_id, updated_at DESC)"
        ),
    ):
        try:
            connection.execute(statement)
        except sqlite3.OperationalError:
            # Older in-place schemas may not have v2 Path tables yet. Migration
            # creates them before final validation; clean v2 databases will
            # apply these indexes normally.
            pass


def _validate_clean_schema(connection: sqlite3.Connection, *, require_path_tables: bool = True) -> None:
    table_names = _table_names(connection)
    leaked_tables = LEGACY_STORAGE_TABLES.intersection(table_names)
    if leaked_tables:
        _drop_legacy_storage_tables(connection)
        table_names = _table_names(connection)

    required_tables = {
        "storage_metadata",
        "personal_models",
        "states",
        "current_state_bindings",
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
    }
    if require_path_tables:
        required_tables.update(
            {
                "paths",
                "path_steps",
                "learning_summaries",
                "understanding_checks",
            }
        )
    missing_tables = required_tables.difference(table_names)
    if missing_tables:
        joined = ", ".join(sorted(missing_tables))
        raise RuntimeError(f"clean storage schema is missing required tables: {joined}")

    _require_columns(
        connection,
        "states",
        {
            "elephant_id",
            "elephant_name",
            "elephant_identity_text",
            "current_context_note",
        },
    )
    _require_columns(
        connection,
        "episodes",
        {
            "updated_at",
            "elephant_id",
            "parent_episode_id",
            "interruption_state",
        },
    )
    _require_columns(
        connection,
        "learning_jobs",
        {"loop_id", "result_json"},
    )
    _require_columns(
        connection,
        "personal_model_facts",
        {"last_accessed_at", "access_count"},
    )
    _require_columns(
        connection,
        "semantic_index_entries",
        {"source_id"},
    )
    if require_path_tables:
        _require_columns(
            connection,
            "paths",
            {"review_mode", "owner_elephant_id", "metadata_json"},
        )
        _require_columns(
            connection,
            "path_steps",
            {
                "assignee_elephant_id",
                "creator_elephant_id",
                "related_episode_id",
                "related_loop_id",
                "completed_at",
            },
        )
        _require_columns(
            connection,
            "learning_summaries",
            {"what_done", "why_it_matters", "how_it_was_done", "knowledge", "human_takeaway"},
        )
        _require_columns(
            connection,
            "understanding_checks",
            {"summary_id", "status", "checked_at"},
        )


def _migrate_schema_1_to_2(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS paths (
            path_id TEXT PRIMARY KEY,
            personal_model_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'paused', 'completed', 'dropped')),
            priority TEXT NOT NULL DEFAULT 'normal',
            review_mode TEXT NOT NULL DEFAULT 'ask_first'
                CHECK(review_mode IN ('ask_first', 'trusted')),
            owner_elephant_id TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_paths_pm_status_updated
            ON paths(personal_model_id, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_paths_owner_updated
            ON paths(owner_elephant_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS path_steps (
            path_step_id TEXT PRIMARY KEY,
            path_id TEXT NOT NULL,
            personal_model_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'next'
                CHECK(status IN ('later', 'next', 'moving', 'checking', 'done', 'stuck', 'dropped')),
            order_index INTEGER NOT NULL DEFAULT 0 CHECK(order_index >= 0),
            assignee_elephant_id TEXT NOT NULL DEFAULT '',
            creator_elephant_id TEXT NOT NULL DEFAULT '',
            due_at TEXT,
            related_episode_id TEXT,
            related_loop_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY(path_id) REFERENCES paths(path_id) ON DELETE CASCADE,
            FOREIGN KEY(personal_model_id) REFERENCES personal_models(personal_model_id)
                ON DELETE CASCADE,
            FOREIGN KEY(related_episode_id) REFERENCES episodes(episode_id) ON DELETE SET NULL,
            FOREIGN KEY(related_loop_id) REFERENCES loops(loop_id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_path_steps_path_status_order
            ON path_steps(path_id, status, order_index, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_path_steps_pm_status_updated
            ON path_steps(personal_model_id, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_path_steps_assignee_status_updated
            ON path_steps(assignee_elephant_id, status, updated_at DESC);

        CREATE TABLE IF NOT EXISTS learning_summaries (
            summary_id TEXT PRIMARY KEY,
            path_step_id TEXT NOT NULL,
            path_id TEXT NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            summary_type TEXT NOT NULL DEFAULT 'task',
            what_done TEXT NOT NULL DEFAULT '',
            why_it_matters TEXT NOT NULL DEFAULT '',
            how_it_was_done TEXT NOT NULL DEFAULT '',
            knowledge TEXT NOT NULL DEFAULT '',
            human_takeaway TEXT NOT NULL DEFAULT '',
            created_by_elephant_id TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(path_step_id) REFERENCES path_steps(path_step_id) ON DELETE CASCADE,
            FOREIGN KEY(path_id) REFERENCES paths(path_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_learning_summaries_step_created
            ON learning_summaries(path_step_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_learning_summaries_path_created
            ON learning_summaries(path_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS understanding_checks (
            check_id TEXT PRIMARY KEY,
            path_step_id TEXT NOT NULL,
            summary_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'understood', 'needs_clarification', 'skipped')),
            checked_by TEXT NOT NULL DEFAULT 'user',
            checked_at TEXT,
            note TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(path_step_id) REFERENCES path_steps(path_step_id) ON DELETE CASCADE,
            FOREIGN KEY(summary_id) REFERENCES learning_summaries(summary_id) ON DELETE CASCADE,
            UNIQUE(summary_id, checked_by)
        );
        CREATE INDEX IF NOT EXISTS idx_understanding_checks_step_updated
            ON understanding_checks(path_step_id, updated_at DESC);
        """
    )
    _write_schema_version(connection, SCHEMA_VERSION)


def _require_columns(
    connection: sqlite3.Connection,
    table_name: str,
    column_names: set[str],
) -> None:
    existing_columns = set(_table_columns(connection, table_name))
    missing_columns = column_names.difference(existing_columns)
    if missing_columns:
        joined = ", ".join(sorted(missing_columns))
        raise RuntimeError(f"clean storage table {table_name} is missing columns: {joined}")


def _table_names(connection: sqlite3.Connection) -> set[str]:
    try:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {str(row["name"]) for row in rows}


def _drop_legacy_storage_tables(connection: sqlite3.Connection) -> tuple[str, ...]:
    existing = LEGACY_STORAGE_TABLES.intersection(_table_names(connection))
    for table_name in sorted(existing):
        connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    return tuple(sorted(existing))


def _table_columns(connection: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    try:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.OperationalError:
        return ()
    return tuple(str(row["name"]) for row in rows)


@contextmanager
def connection(self) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(self.database_path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        yield connection
    finally:
        connection.close()


def schema_version(self, connection: sqlite3.Connection | None = None) -> int:
    if connection is None:
        with self.connection() as owned_connection:
            return self.schema_version(owned_connection)
    try:
        row = connection.execute(
            """
            SELECT metadata_value AS version
            FROM storage_metadata
            WHERE metadata_key = 'schema_version'
            """
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None or row["version"] is None:
        return 0
    return int(row["version"])
