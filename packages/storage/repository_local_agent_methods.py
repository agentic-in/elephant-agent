"""Persistence methods for local agent runtime discovery."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import TYPE_CHECKING, Mapping, Sequence

if TYPE_CHECKING:
    from packages.operator.local_agents import LocalAgentRuntimeRecord


def upsert_local_agent_runtime(self, record: "LocalAgentRuntimeRecord") -> None:
    with self.connection() as connection:
        _ensure_local_agent_runtime_table(connection)
        connection.execute(
            """
            INSERT INTO local_agent_runtimes (
                runtime_id,
                provider_id,
                command,
                display_name,
                resolved_path,
                version,
                status,
                auth_status,
                source,
                default_model,
                can_execute,
                role_title,
                role_prompt,
                detected_at,
                last_error,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(runtime_id) DO UPDATE SET
                provider_id = excluded.provider_id,
                command = excluded.command,
                display_name = excluded.display_name,
                resolved_path = excluded.resolved_path,
                version = excluded.version,
                status = excluded.status,
                auth_status = excluded.auth_status,
                source = excluded.source,
                default_model = excluded.default_model,
                can_execute = excluded.can_execute,
                role_title = excluded.role_title,
                role_prompt = excluded.role_prompt,
                detected_at = excluded.detected_at,
                last_error = excluded.last_error,
                metadata_json = excluded.metadata_json
            """,
            _record_values(record),
        )
        connection.commit()


def upsert_local_agent_runtimes(self, records: Sequence["LocalAgentRuntimeRecord"]) -> None:
    with self.connection() as connection:
        _ensure_local_agent_runtime_table(connection)
        for record in records:
            connection.execute(
                """
                INSERT INTO local_agent_runtimes (
                    runtime_id,
                    provider_id,
                    command,
                    display_name,
                    resolved_path,
                    version,
                    status,
                    auth_status,
                    source,
                    default_model,
                    can_execute,
                    role_title,
                    role_prompt,
                    detected_at,
                    last_error,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(runtime_id) DO UPDATE SET
                    provider_id = excluded.provider_id,
                    command = excluded.command,
                    display_name = excluded.display_name,
                    resolved_path = excluded.resolved_path,
                    version = excluded.version,
                    status = excluded.status,
                    auth_status = excluded.auth_status,
                    source = excluded.source,
                    default_model = excluded.default_model,
                    can_execute = excluded.can_execute,
                    role_title = excluded.role_title,
                    role_prompt = excluded.role_prompt,
                    detected_at = excluded.detected_at,
                    last_error = excluded.last_error,
                    metadata_json = excluded.metadata_json
                """,
                _record_values(record),
            )
        connection.commit()


def load_local_agent_runtime(self, runtime_id: str) -> "LocalAgentRuntimeRecord | None":
    with self.connection() as connection:
        _ensure_local_agent_runtime_table(connection)
        connection.commit()
        row = connection.execute(
            "SELECT * FROM local_agent_runtimes WHERE runtime_id = ?",
            (runtime_id,),
        ).fetchone()
    return None if row is None else _record_from_row(row)


def list_local_agent_runtimes(self) -> tuple["LocalAgentRuntimeRecord", ...]:
    with self.connection() as connection:
        _ensure_local_agent_runtime_table(connection)
        connection.commit()
        rows: Sequence[object] = connection.execute(
            """
            SELECT *
            FROM local_agent_runtimes
            ORDER BY provider_id ASC, resolved_path ASC
            """
        ).fetchall()
    return tuple(_record_from_row(row) for row in rows)


def _ensure_local_agent_runtime_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS local_agent_runtimes (
            runtime_id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            command TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            resolved_path TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'detected',
            auth_status TEXT NOT NULL DEFAULT 'unknown',
            source TEXT NOT NULL DEFAULT 'path',
            default_model TEXT NOT NULL DEFAULT '',
            can_execute INTEGER NOT NULL DEFAULT 0,
            role_title TEXT NOT NULL DEFAULT '',
            role_prompt TEXT NOT NULL DEFAULT '',
            detected_at TEXT NOT NULL,
            last_error TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_local_agent_runtimes_provider
        ON local_agent_runtimes(provider_id, status)
        """
    )


def _record_values(record: "LocalAgentRuntimeRecord") -> tuple[object, ...]:
    return (
        record.runtime_id,
        record.provider_id,
        record.command,
        record.display_name,
        record.resolved_path,
        record.version,
        record.status,
        record.auth_status,
        record.source,
        record.default_model,
        1 if record.can_execute else 0,
        record.role_title,
        record.role_prompt,
        record.detected_at or datetime.now(timezone.utc).isoformat(),
        record.last_error,
        json.dumps(dict(record.metadata), separators=(",", ":"), sort_keys=True),
    )


def _record_from_row(row: sqlite3.Row) -> "LocalAgentRuntimeRecord":
    from packages.operator.local_agents import LocalAgentRuntimeRecord

    return LocalAgentRuntimeRecord(
        runtime_id=str(row["runtime_id"]),
        provider_id=str(row["provider_id"]),
        command=str(row["command"]),
        display_name=str(row["display_name"]),
        resolved_path=str(row["resolved_path"]),
        version=str(row["version"]),
        status=str(row["status"]),
        auth_status=str(row["auth_status"]),
        source=str(row["source"]),
        default_model=str(row["default_model"]),
        can_execute=bool(row["can_execute"]),
        role_title=str(row["role_title"]),
        role_prompt=str(row["role_prompt"]),
        detected_at=str(row["detected_at"]),
        last_error=str(row["last_error"]),
        metadata=_mapping(str(row["metadata_json"])),
    )


def _mapping(payload: str) -> Mapping[str, str]:
    data = json.loads(payload or "{}")
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


__all__ = [
    "list_local_agent_runtimes",
    "load_local_agent_runtime",
    "upsert_local_agent_runtime",
    "upsert_local_agent_runtimes",
]
