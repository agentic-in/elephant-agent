"""Repository methods for Path step comments."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence
from uuid import uuid4

from packages.contracts.paths import PathStepCommentRecord

from .repository_support import (
    _iso,
    _json_mapping,
    _path_step_comment_from_row,
    canonical_personal_model_id,
)


def create_path_step_comment(
    self,
    *,
    path_step_id: str,
    body: str,
    author_kind: str = "user",
    author_id: str = "",
    comment_type: str = "comment",
    run_id: str = "",
    parent_comment_id: str = "",
    metadata: dict[str, str] | None = None,
    comment_id: str | None = None,
) -> PathStepCommentRecord:
    step = self.load_path_step(path_step_id)
    if step is None:
        raise KeyError(path_step_id)
    record = PathStepCommentRecord(
        comment_id=comment_id or f"path-step-comment-{uuid4().hex}",
        path_step_id=path_step_id,
        path_id=step.path_id,
        personal_model_id=step.personal_model_id,
        body=body,
        author_kind=author_kind,
        author_id=author_id,
        comment_type=comment_type,
        run_id=run_id,
        parent_comment_id=parent_comment_id,
        metadata=metadata or {},
    )
    self.upsert_path_step_comment(record)
    loaded = self.load_path_step_comment(record.comment_id)
    if loaded is None:
        raise RuntimeError("Path step comment was not persisted")
    return loaded


def upsert_path_step_comment(
    self,
    record: PathStepCommentRecord,
    *,
    updated_at: datetime | None = None,
) -> None:
    timestamp = _iso(updated_at)
    created_at = _iso(record.created_at) if record.created_at is not None else timestamp
    updated = _iso(record.updated_at) if record.updated_at is not None else timestamp
    with self.connection() as connection:
        existing = connection.execute(
            "SELECT created_at FROM path_step_comments WHERE comment_id = ?",
            (record.comment_id,),
        ).fetchone()
        if existing is not None:
            created_at = str(existing["created_at"])
        connection.execute(
            """
            INSERT INTO path_step_comments (
                comment_id,
                path_step_id,
                path_id,
                personal_model_id,
                body,
                author_kind,
                author_id,
                comment_type,
                run_id,
                parent_comment_id,
                metadata_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(comment_id) DO UPDATE SET
                path_step_id = excluded.path_step_id,
                path_id = excluded.path_id,
                personal_model_id = excluded.personal_model_id,
                body = excluded.body,
                author_kind = excluded.author_kind,
                author_id = excluded.author_id,
                comment_type = excluded.comment_type,
                run_id = excluded.run_id,
                parent_comment_id = excluded.parent_comment_id,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                record.comment_id,
                record.path_step_id,
                record.path_id,
                canonical_personal_model_id(record.personal_model_id),
                record.body,
                record.author_kind,
                record.author_id,
                record.comment_type,
                record.run_id,
                record.parent_comment_id,
                _json_mapping(dict(record.metadata)),
                created_at,
                updated,
            ),
        )
        connection.execute(
            "UPDATE paths SET updated_at = ? WHERE path_id = ?",
            (timestamp, record.path_id),
        )
        connection.commit()


def load_path_step_comment(self, comment_id: str) -> PathStepCommentRecord | None:
    with self.connection() as connection:
        row = connection.execute(
            _PATH_STEP_COMMENT_SELECT + " WHERE comment_id = ?",
            (comment_id,),
        ).fetchone()
    return _path_step_comment_from_row(row) if row is not None else None


def list_path_step_comments(
    self,
    *,
    path_step_id: str | None = None,
    path_id: str | None = None,
    run_id: str | None = None,
    author_kind: str | None = None,
    limit: int | None = None,
) -> tuple[PathStepCommentRecord, ...]:
    clauses: list[str] = []
    params: list[object] = []
    if path_step_id:
        clauses.append("path_step_id = ?")
        params.append(path_step_id)
    if path_id:
        clauses.append("path_id = ?")
        params.append(path_id)
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if author_kind:
        clauses.append("author_kind = ?")
        params.append(author_kind)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    if limit is not None:
        sql = (
            "SELECT * FROM ("
            + _PATH_STEP_COMMENT_SELECT
            + where
            + " ORDER BY created_at DESC, comment_id DESC LIMIT ?"
            + ") ORDER BY created_at ASC, comment_id ASC"
        )
        params.append(max(1, int(limit)))
    else:
        sql = _PATH_STEP_COMMENT_SELECT + where + " ORDER BY created_at ASC, comment_id ASC"
    with self.connection() as connection:
        rows: Sequence[object] = connection.execute(sql, tuple(params)).fetchall()
    return tuple(_path_step_comment_from_row(row) for row in rows)

_PATH_STEP_COMMENT_SELECT = """
    SELECT comment_id, path_step_id, path_id, personal_model_id, body,
           author_kind, author_id, comment_type, run_id, parent_comment_id,
           metadata_json, created_at, updated_at
    FROM path_step_comments
"""
