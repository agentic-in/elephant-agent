"""Semantic index backend contracts and SQLite sqlite-vec implementation."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterator, Mapping, Protocol

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_]\w*$")

from .sqlite_vec import SQLiteVecLoadState, load_sqlite_vec_extension


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class SemanticIndexHealth:
    status: str
    summary: str
    vector_available: bool
    lexical_available: bool = False
    checked_at: datetime = field(default_factory=_utc_now)
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.status == "ready" and self.vector_available


@dataclass(frozen=True, slots=True)
class SemanticIndexVector:
    semantic_index_entry_id: str
    dimensions: int
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.semantic_index_entry_id.strip():
            raise ValueError("semantic index entry id must not be empty")
        if self.dimensions <= 0:
            raise ValueError("semantic index vector dimensions must be positive")
        if len(self.values) != self.dimensions:
            raise ValueError("semantic index vector length must match dimensions")


@dataclass(frozen=True, slots=True)
class SemanticIndexVectorQuery:
    dimensions: int
    values: tuple[float, ...]
    limit: int = 10

    def __post_init__(self) -> None:
        if self.dimensions <= 0:
            raise ValueError("semantic index query dimensions must be positive")
        if len(self.values) != self.dimensions:
            raise ValueError("semantic index query vector length must match dimensions")
        if self.limit <= 0:
            raise ValueError("semantic index query limit must be positive")


@dataclass(frozen=True, slots=True)
class SemanticIndexVectorMatch:
    semantic_index_entry_id: str
    distance: float
    score: float
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SemanticIndexDeleteRequest:
    semantic_index_entry_ids: tuple[str, ...]
    dimensions: int | None = None

    def __post_init__(self) -> None:
        if not self.semantic_index_entry_ids:
            raise ValueError("semantic index delete request requires entry ids")
        if self.dimensions is not None and self.dimensions <= 0:
            raise ValueError("semantic index delete dimensions must be positive")


@dataclass(frozen=True, slots=True)
class SemanticIndexWriteResult:
    status: str
    accepted: int
    summary: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def degraded(self) -> bool:
        return self.status == "degraded"


@dataclass(frozen=True, slots=True)
class SemanticIndexRebuildPlan:
    rebuild_entry_ids: tuple[str, ...] = ()
    reuse_entry_ids: tuple[str, ...] = ()
    delete_entry_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


class SemanticIndexBackend(Protocol):
    def health(self) -> SemanticIndexHealth:
        """Return semantic-index backend health."""

    def upsert(self, vector: SemanticIndexVector) -> SemanticIndexWriteResult:
        """Insert or replace one indexed vector."""

    def search(self, query: SemanticIndexVectorQuery) -> tuple[SemanticIndexVectorMatch, ...]:
        """Search indexed vectors for a query vector."""

    def delete(self, request: SemanticIndexDeleteRequest) -> SemanticIndexWriteResult:
        """Delete indexed vectors by entry id."""

    def rebuild_plan(
        self,
        *,
        current: tuple[SemanticIndexVector, ...],
        desired: tuple[SemanticIndexVector, ...],
    ) -> SemanticIndexRebuildPlan:
        """Return deterministic vector rebuild work for current and desired entries."""


class SQLiteVecSemanticIndex:
    backend_id = "sqlite-vec"

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def health(self) -> SemanticIndexHealth:
        with self._connect() as connection:
            state = load_sqlite_vec_extension(connection)
        if not state.ready:
            return SemanticIndexHealth(
                status="degraded",
                summary=state.summary,
                vector_available=False,
                lexical_available=True,
                metadata=dict(state.metadata),
            )
        return SemanticIndexHealth(
            status="ready",
            summary="sqlite-vec semantic index is ready.",
            vector_available=True,
            lexical_available=True,
            metadata=dict(state.metadata),
        )

    def upsert(self, vector: SemanticIndexVector) -> SemanticIndexWriteResult:
        with self._loaded_connection() as (connection, state):
            if not state.ready:
                return _degraded_write(state.summary, state.metadata)
            table_name = _vector_table_name(vector.dimensions)
            _ensure_vector_table(connection, table_name, vector.dimensions)
            rowid = _vector_rowid(vector.semantic_index_entry_id)
            connection.execute(
                "DELETE FROM " + table_name + " WHERE semantic_index_entry_id = ?",
                (vector.semantic_index_entry_id,),
            )
            connection.execute(
                "INSERT INTO " + table_name + "(rowid, semantic_index_entry_id, embedding)"
                " VALUES (?, ?, ?)",
                (rowid, vector.semantic_index_entry_id, _vector_json(vector.values)),
            )
            connection.commit()
        return SemanticIndexWriteResult(
            status="indexed",
            accepted=1,
            summary="semantic vector indexed through sqlite-vec.",
            metadata={"backend": self.backend_id, "dimensions": str(vector.dimensions)},
        )

    def search(self, query: SemanticIndexVectorQuery) -> tuple[SemanticIndexVectorMatch, ...]:
        with self._loaded_connection() as (connection, state):
            if not state.ready:
                return ()
            table_name = _vector_table_name(query.dimensions)
            if not _table_exists(connection, table_name):
                return ()
            rows = connection.execute(
                "SELECT semantic_index_entry_id, distance"
                + " FROM " + table_name
                + " WHERE embedding MATCH ? AND k = ?"
                + " ORDER BY distance ASC",
                (_vector_json(query.values), query.limit),
            ).fetchall()
        return tuple(
            SemanticIndexVectorMatch(
                semantic_index_entry_id=str(row["semantic_index_entry_id"]),
                distance=float(row["distance"]),
                score=1.0 / (1.0 + max(0.0, float(row["distance"]))),
                metadata={"signal": "vector"},
            )
            for row in rows
        )

    def delete(self, request: SemanticIndexDeleteRequest) -> SemanticIndexWriteResult:
        with self._loaded_connection() as (connection, state):
            if not state.ready:
                return _degraded_write(state.summary, state.metadata)
            table_names = (
                (_vector_table_name(request.dimensions),)
                if request.dimensions is not None
                else _vector_table_names(connection)
            )
            deleted = 0
            for table_name in table_names:
                for entry_id in request.semantic_index_entry_ids:
                    cursor = connection.execute(
                        "DELETE FROM " + table_name + " WHERE rowid = ?",
                        (_vector_rowid(entry_id),),
                    )
                    deleted += int(cursor.rowcount)
            connection.commit()
        return SemanticIndexWriteResult(
            status="deleted",
            accepted=deleted,
            summary="semantic vectors deleted through sqlite-vec.",
            metadata={"backend": self.backend_id},
        )

    def rebuild_plan(
        self,
        *,
        current: tuple[SemanticIndexVector, ...],
        desired: tuple[SemanticIndexVector, ...],
    ) -> SemanticIndexRebuildPlan:
        current_by_id = {entry.semantic_index_entry_id: entry for entry in current}
        desired_by_id = {entry.semantic_index_entry_id: entry for entry in desired}
        rebuild = tuple(
            entry_id
            for entry_id, desired_entry in sorted(desired_by_id.items())
            if current_by_id.get(entry_id) != desired_entry
        )
        reuse = tuple(
            entry_id
            for entry_id, desired_entry in sorted(desired_by_id.items())
            if current_by_id.get(entry_id) == desired_entry
        )
        delete = tuple(sorted(set(current_by_id) - set(desired_by_id)))
        return SemanticIndexRebuildPlan(
            rebuild_entry_ids=rebuild,
            reuse_entry_ids=reuse,
            delete_entry_ids=delete,
            metadata={"comparison": "vector-payload"},
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _loaded_connection(self) -> Iterator[tuple[sqlite3.Connection, SQLiteVecLoadState]]:
        with self._connect() as connection:
            yield connection, load_sqlite_vec_extension(connection)


def _ensure_vector_table(connection: sqlite3.Connection, table_name: str, dimensions: int) -> None:
    connection.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS " + table_name
        + " USING vec0(+semantic_index_entry_id TEXT, embedding FLOAT[" + str(dimensions) + "])"
    )


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _vector_table_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name LIKE 'semantic_index_vec_%'
        ORDER BY name ASC
        """
    ).fetchall()
    return tuple(str(row["name"]) for row in rows)


def _vector_table_name(dimensions: int) -> str:
    if dimensions <= 0:
        raise ValueError("semantic index vector dimensions must be positive")
    name = f"semantic_index_vec_{dimensions}"
    if not _IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"invalid table name derived from dimensions: {name}")
    return name


def _vector_rowid(entry_id: str) -> int:
    digest = hashlib.sha256(entry_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def _vector_json(values: tuple[float, ...]) -> str:
    return json.dumps([float(value) for value in values], separators=(",", ":"))


def _degraded_write(summary: str, metadata: Mapping[str, str]) -> SemanticIndexWriteResult:
    return SemanticIndexWriteResult(
        status="degraded",
        accepted=0,
        summary=summary,
        metadata={str(key): str(value) for key, value in metadata.items()},
    )
