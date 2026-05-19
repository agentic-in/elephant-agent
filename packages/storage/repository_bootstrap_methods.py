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
                f"database schema version {version} is newer than supported schema version {SCHEMA_VERSION}"
            )
        if version == 0:
            _drop_legacy_storage_tables(connection)
            _require_empty_database(connection)
            _install_clean_schema(connection)
            _validate_clean_schema(connection)
            connection.commit()
        elif version == SCHEMA_VERSION:
            _drop_legacy_storage_tables(connection)
            try:
                _validate_clean_schema(connection)
            except RuntimeError:
                _reset_storage_schema(connection)
                _validate_clean_schema(connection)
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
            "existing storage database has no clean schema marker; reset runtime storage before bootstrapping"
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


def _validate_clean_schema(connection: sqlite3.Connection) -> None:
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
