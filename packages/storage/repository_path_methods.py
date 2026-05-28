"""Repository methods for durable user-facing Paths."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Sequence
from uuid import uuid4

from packages.contracts.paths import (
    PathRecord,
    PathStepRecord,
)

from .repository_support import (
    DEFAULT_PERSONAL_MODEL_ID,
    _iso,
    _json_mapping,
    _path_from_row,
    _path_step_from_row,
    canonical_personal_model_id,
)


def create_path(
    self,
    *,
    personal_model_id: str = DEFAULT_PERSONAL_MODEL_ID,
    title: str,
    description: str = "",
    priority: str = "normal",
    review_mode: str = "trusted",
    owner_elephant_id: str = "",
    metadata: dict[str, str] | None = None,
    path_id: str | None = None,
) -> PathRecord:
    canonical_id = canonical_personal_model_id(personal_model_id)
    self.ensure_default_personal_model(personal_model_id=canonical_id)
    record = PathRecord(
        path_id=path_id or f"path-{uuid4().hex}",
        personal_model_id=canonical_id,
        title=title,
        description=description,
        priority=priority,
        review_mode=review_mode,
        owner_elephant_id=owner_elephant_id,
        metadata=metadata or {},
    )
    self.upsert_path(record)
    loaded = self.load_path(record.path_id)
    if loaded is None:
        raise RuntimeError("Path was not persisted")
    return loaded


def upsert_path(self, record: PathRecord, *, updated_at: datetime | None = None) -> None:
    canonical_id = canonical_personal_model_id(record.personal_model_id)
    self.ensure_default_personal_model(personal_model_id=canonical_id)
    timestamp = _iso(updated_at)
    created_at = _iso(record.created_at) if record.created_at is not None else timestamp
    updated = _iso(record.updated_at) if record.updated_at is not None else timestamp
    with self.connection() as connection:
        existing = connection.execute(
            "SELECT created_at FROM paths WHERE path_id = ?",
            (record.path_id,),
        ).fetchone()
        if existing is not None:
            created_at = str(existing["created_at"])
        connection.execute(
            """
            INSERT INTO paths (
                path_id,
                personal_model_id,
                title,
                description,
                status,
                priority,
                review_mode,
                owner_elephant_id,
                metadata_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path_id) DO UPDATE SET
                personal_model_id = excluded.personal_model_id,
                title = excluded.title,
                description = excluded.description,
                status = excluded.status,
                priority = excluded.priority,
                review_mode = excluded.review_mode,
                owner_elephant_id = excluded.owner_elephant_id,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                record.path_id,
                canonical_id,
                record.title,
                record.description,
                record.status,
                record.priority,
                record.review_mode,
                record.owner_elephant_id,
                _json_mapping(dict(record.metadata)),
                created_at,
                updated,
            ),
        )
        connection.commit()


def load_path(self, path_id: str) -> PathRecord | None:
    with self.connection() as connection:
        row = connection.execute(
            """
            SELECT path_id, personal_model_id, title, description, status, priority,
                   review_mode, owner_elephant_id, metadata_json, created_at, updated_at
            FROM paths
            WHERE path_id = ?
            """,
            (path_id,),
        ).fetchone()
    return _path_from_row(row) if row is not None else None


def list_paths(
    self,
    *,
    personal_model_id: str | None = None,
    status: str | tuple[str, ...] | None = None,
    limit: int | None = None,
) -> tuple[PathRecord, ...]:
    clauses: list[str] = []
    params: list[object] = []
    if personal_model_id:
        clauses.append("personal_model_id = ?")
        params.append(canonical_personal_model_id(personal_model_id))
    if status:
        statuses = (status,) if isinstance(status, str) else tuple(status)
        placeholders = ", ".join("?" for _ in statuses)
        clauses.append(f"status IN ({placeholders})")
        params.extend(statuses)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        "SELECT path_id, personal_model_id, title, description, status, priority, "
        "review_mode, owner_elephant_id, metadata_json, created_at, updated_at "
        f"FROM paths {where} ORDER BY updated_at DESC, created_at DESC, path_id ASC"
    )
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))
    with self.connection() as connection:
        rows: Sequence[object] = connection.execute(sql, tuple(params)).fetchall()
    return tuple(_path_from_row(row) for row in rows)


def delete_path(self, path_id: str) -> bool:
    with self.connection() as connection:
        cursor = connection.execute(
            "DELETE FROM paths WHERE path_id = ?",
            (path_id,),
        )
        connection.commit()
    return cursor.rowcount > 0


def create_path_step(
    self,
    *,
    path_id: str,
    title: str,
    description: str = "",
    status: str = "next",
    order_index: int | None = None,
    assignee_elephant_id: str = "",
    creator_elephant_id: str = "",
    due_at: datetime | None = None,
    related_episode_id: str | None = None,
    related_loop_id: str | None = None,
    metadata: dict[str, str] | None = None,
    path_step_id: str | None = None,
) -> PathStepRecord:
    path = self.load_path(path_id)
    if path is None:
        raise KeyError(path_id)
    if order_index is None:
        existing = self.list_path_steps(path_id=path_id)
        order_index = len(existing)
    record = PathStepRecord(
        path_step_id=path_step_id or f"path-step-{uuid4().hex}",
        path_id=path_id,
        personal_model_id=path.personal_model_id,
        title=title,
        description=description,
        status=status,
        order_index=max(0, int(order_index)),
        assignee_elephant_id=assignee_elephant_id,
        creator_elephant_id=creator_elephant_id,
        due_at=due_at,
        related_episode_id=related_episode_id,
        related_loop_id=related_loop_id,
        metadata=metadata or {},
    )
    self.upsert_path_step(record)
    loaded = self.load_path_step(record.path_step_id)
    if loaded is None:
        raise RuntimeError("Path step was not persisted")
    return loaded


def upsert_path_step(self, record: PathStepRecord, *, updated_at: datetime | None = None) -> None:
    timestamp = _iso(updated_at)
    created_at = _iso(record.created_at) if record.created_at is not None else timestamp
    updated = _iso(record.updated_at) if record.updated_at is not None else timestamp
    completed_at = _iso(record.completed_at) if record.completed_at is not None else None
    if record.status == "done" and completed_at is None:
        completed_at = updated
    with self.connection() as connection:
        existing = connection.execute(
            "SELECT created_at, completed_at FROM path_steps WHERE path_step_id = ?",
            (record.path_step_id,),
        ).fetchone()
        if existing is not None:
            created_at = str(existing["created_at"])
            if completed_at is None and existing["completed_at"] is not None:
                completed_at = str(existing["completed_at"])
        connection.execute(
            """
            INSERT INTO path_steps (
                path_step_id,
                path_id,
                personal_model_id,
                title,
                description,
                status,
                order_index,
                assignee_elephant_id,
                creator_elephant_id,
                due_at,
                related_episode_id,
                related_loop_id,
                metadata_json,
                created_at,
                updated_at,
                completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path_step_id) DO UPDATE SET
                path_id = excluded.path_id,
                personal_model_id = excluded.personal_model_id,
                title = excluded.title,
                description = excluded.description,
                status = excluded.status,
                order_index = excluded.order_index,
                assignee_elephant_id = excluded.assignee_elephant_id,
                creator_elephant_id = excluded.creator_elephant_id,
                due_at = excluded.due_at,
                related_episode_id = excluded.related_episode_id,
                related_loop_id = excluded.related_loop_id,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at,
                completed_at = CASE
                    WHEN excluded.status = 'done' THEN COALESCE(path_steps.completed_at, excluded.completed_at)
                    WHEN excluded.status != 'done' THEN NULL
                    ELSE excluded.completed_at
                END
            """,
            (
                record.path_step_id,
                record.path_id,
                canonical_personal_model_id(record.personal_model_id),
                record.title,
                record.description,
                record.status,
                int(record.order_index),
                record.assignee_elephant_id,
                record.creator_elephant_id,
                _iso(record.due_at) if record.due_at is not None else None,
                record.related_episode_id,
                record.related_loop_id,
                _json_mapping(dict(record.metadata)),
                created_at,
                updated,
                completed_at,
            ),
        )
        connection.execute(
            "UPDATE paths SET updated_at = ? WHERE path_id = ?",
            (updated, record.path_id),
        )
        connection.commit()


def load_path_step(self, path_step_id: str) -> PathStepRecord | None:
    with self.connection() as connection:
        row = connection.execute(_PATH_STEP_SELECT + " WHERE path_step_id = ?", (path_step_id,)).fetchone()
    return _path_step_from_row(row) if row is not None else None


def list_path_steps(
    self,
    *,
    path_id: str | None = None,
    personal_model_id: str | None = None,
    status: str | tuple[str, ...] | None = None,
    assignee_elephant_id: str | None = None,
    limit: int | None = None,
) -> tuple[PathStepRecord, ...]:
    clauses: list[str] = []
    params: list[object] = []
    if path_id:
        clauses.append("path_id = ?")
        params.append(path_id)
    if personal_model_id:
        clauses.append("personal_model_id = ?")
        params.append(canonical_personal_model_id(personal_model_id))
    if assignee_elephant_id:
        clauses.append("assignee_elephant_id = ?")
        params.append(assignee_elephant_id)
    if status:
        statuses = (status,) if isinstance(status, str) else tuple(status)
        placeholders = ", ".join("?" for _ in statuses)
        clauses.append(f"status IN ({placeholders})")
        params.extend(statuses)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = _PATH_STEP_SELECT + where + " ORDER BY order_index ASC, updated_at DESC, path_step_id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))
    with self.connection() as connection:
        rows: Sequence[object] = connection.execute(sql, tuple(params)).fetchall()
    return tuple(_path_step_from_row(row) for row in rows)


def delete_path_step(self, path_step_id: str) -> bool:
    existing = self.load_path_step(path_step_id)
    if existing is None:
        return False
    with self.connection() as connection:
        cursor = connection.execute(
            "DELETE FROM path_steps WHERE path_step_id = ?",
            (path_step_id,),
        )
        connection.execute(
            "UPDATE paths SET updated_at = ? WHERE path_id = ?",
            (_iso(None), existing.path_id),
        )
        connection.commit()
    return cursor.rowcount > 0

_PATH_STEP_SELECT = """
    SELECT path_step_id, path_id, personal_model_id, title, description, status,
           order_index, assignee_elephant_id, creator_elephant_id, due_at,
           related_episode_id, related_loop_id, metadata_json, created_at,
           updated_at, completed_at
    FROM path_steps
"""
