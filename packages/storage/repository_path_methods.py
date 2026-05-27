"""Repository methods for durable user-facing Paths."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence
from uuid import uuid4

from packages.contracts.paths import (
    LearningSummaryRecord,
    PathRecord,
    PathStepRecord,
    UnderstandingCheckRecord,
)

from .repository_support import (
    DEFAULT_PERSONAL_MODEL_ID,
    _iso,
    _json_mapping,
    _learning_summary_from_row,
    _path_from_row,
    _path_step_from_row,
    _understanding_check_from_row,
    canonical_personal_model_id,
)


def create_path(
    self,
    *,
    personal_model_id: str = DEFAULT_PERSONAL_MODEL_ID,
    title: str,
    description: str = "",
    priority: str = "normal",
    review_mode: str = "ask_first",
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


def write_learning_summary(
    self,
    *,
    path_step_id: str,
    what_done: str,
    why_it_matters: str = "",
    how_it_was_done: str = "",
    knowledge: str = "",
    human_takeaway: str = "",
    run_id: str = "",
    summary_type: str = "task",
    created_by_elephant_id: str = "",
    metadata: dict[str, str] | None = None,
    summary_id: str | None = None,
) -> LearningSummaryRecord:
    step = self.load_path_step(path_step_id)
    if step is None:
        raise KeyError(path_step_id)
    record = LearningSummaryRecord(
        summary_id=summary_id or f"learning-summary-{uuid4().hex}",
        path_step_id=path_step_id,
        path_id=step.path_id,
        run_id=run_id,
        summary_type=summary_type,
        what_done=what_done,
        why_it_matters=why_it_matters,
        how_it_was_done=how_it_was_done,
        knowledge=knowledge,
        human_takeaway=human_takeaway,
        created_by_elephant_id=created_by_elephant_id,
        metadata=metadata or {},
    )
    self.upsert_learning_summary(record)
    loaded = self.load_learning_summary(record.summary_id)
    if loaded is None:
        raise RuntimeError("Learning summary was not persisted")
    return loaded


def upsert_learning_summary(self, record: LearningSummaryRecord) -> None:
    timestamp = _iso(record.created_at)
    with self.connection() as connection:
        connection.execute(
            """
            INSERT INTO learning_summaries (
                summary_id,
                path_step_id,
                path_id,
                run_id,
                summary_type,
                what_done,
                why_it_matters,
                how_it_was_done,
                knowledge,
                human_takeaway,
                created_by_elephant_id,
                metadata_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(summary_id) DO UPDATE SET
                path_step_id = excluded.path_step_id,
                path_id = excluded.path_id,
                run_id = excluded.run_id,
                summary_type = excluded.summary_type,
                what_done = excluded.what_done,
                why_it_matters = excluded.why_it_matters,
                how_it_was_done = excluded.how_it_was_done,
                knowledge = excluded.knowledge,
                human_takeaway = excluded.human_takeaway,
                created_by_elephant_id = excluded.created_by_elephant_id,
                metadata_json = excluded.metadata_json
            """,
            (
                record.summary_id,
                record.path_step_id,
                record.path_id,
                record.run_id,
                record.summary_type,
                record.what_done,
                record.why_it_matters,
                record.how_it_was_done,
                record.knowledge,
                record.human_takeaway,
                record.created_by_elephant_id,
                _json_mapping(dict(record.metadata)),
                timestamp,
            ),
        )
        connection.commit()


def load_learning_summary(self, summary_id: str) -> LearningSummaryRecord | None:
    with self.connection() as connection:
        row = connection.execute(_LEARNING_SUMMARY_SELECT + " WHERE summary_id = ?", (summary_id,)).fetchone()
    return _learning_summary_from_row(row) if row is not None else None


def list_learning_summaries(
    self,
    *,
    path_step_id: str | None = None,
    path_id: str | None = None,
    limit: int | None = None,
) -> tuple[LearningSummaryRecord, ...]:
    clauses: list[str] = []
    params: list[object] = []
    if path_step_id:
        clauses.append("path_step_id = ?")
        params.append(path_step_id)
    if path_id:
        clauses.append("path_id = ?")
        params.append(path_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = _LEARNING_SUMMARY_SELECT + where + " ORDER BY created_at DESC, summary_id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))
    with self.connection() as connection:
        rows: Sequence[object] = connection.execute(sql, tuple(params)).fetchall()
    return tuple(_learning_summary_from_row(row) for row in rows)


def write_understanding_check(
    self,
    *,
    summary_id: str,
    status: str = "understood",
    checked_by: str = "user",
    note: str = "",
    metadata: dict[str, str] | None = None,
    check_id: str | None = None,
) -> UnderstandingCheckRecord:
    summary = self.load_learning_summary(summary_id)
    if summary is None:
        raise KeyError(summary_id)
    existing = self.list_understanding_checks(summary_id=summary_id, checked_by=checked_by)
    record = UnderstandingCheckRecord(
        check_id=check_id or (existing[0].check_id if existing else f"understanding-check-{uuid4().hex}"),
        path_step_id=summary.path_step_id,
        summary_id=summary_id,
        status=status,
        checked_by=checked_by,
        checked_at=None,
        note=note,
        metadata=metadata or {},
    )
    self.upsert_understanding_check(record)
    loaded = self.load_understanding_check(record.check_id)
    if loaded is None:
        raise RuntimeError("Understanding check was not persisted")
    return loaded


def upsert_understanding_check(self, record: UnderstandingCheckRecord, *, updated_at: datetime | None = None) -> None:
    timestamp = _iso(updated_at)
    checked_at = _iso(record.checked_at) if record.checked_at is not None else (timestamp if record.status == "understood" else None)
    created_at = _iso(record.created_at) if record.created_at is not None else timestamp
    with self.connection() as connection:
        existing = connection.execute(
            "SELECT created_at FROM understanding_checks WHERE check_id = ?",
            (record.check_id,),
        ).fetchone()
        if existing is not None:
            created_at = str(existing["created_at"])
        connection.execute(
            """
            INSERT INTO understanding_checks (
                check_id,
                path_step_id,
                summary_id,
                status,
                checked_by,
                checked_at,
                note,
                metadata_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(summary_id, checked_by) DO UPDATE SET
                check_id = excluded.check_id,
                path_step_id = excluded.path_step_id,
                status = excluded.status,
                checked_at = excluded.checked_at,
                note = excluded.note,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                record.check_id,
                record.path_step_id,
                record.summary_id,
                record.status,
                record.checked_by,
                checked_at,
                record.note,
                _json_mapping(dict(record.metadata)),
                created_at,
                timestamp,
            ),
        )
        connection.commit()


def load_understanding_check(self, check_id: str) -> UnderstandingCheckRecord | None:
    with self.connection() as connection:
        row = connection.execute(_UNDERSTANDING_CHECK_SELECT + " WHERE check_id = ?", (check_id,)).fetchone()
    return _understanding_check_from_row(row) if row is not None else None


def list_understanding_checks(
    self,
    *,
    path_step_id: str | None = None,
    summary_id: str | None = None,
    checked_by: str | None = None,
    limit: int | None = None,
) -> tuple[UnderstandingCheckRecord, ...]:
    clauses: list[str] = []
    params: list[object] = []
    if path_step_id:
        clauses.append("path_step_id = ?")
        params.append(path_step_id)
    if summary_id:
        clauses.append("summary_id = ?")
        params.append(summary_id)
    if checked_by:
        clauses.append("checked_by = ?")
        params.append(checked_by)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = _UNDERSTANDING_CHECK_SELECT + where + " ORDER BY updated_at DESC, check_id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))
    with self.connection() as connection:
        rows: Sequence[object] = connection.execute(sql, tuple(params)).fetchall()
    return tuple(_understanding_check_from_row(row) for row in rows)


_PATH_STEP_SELECT = """
    SELECT path_step_id, path_id, personal_model_id, title, description, status,
           order_index, assignee_elephant_id, creator_elephant_id, due_at,
           related_episode_id, related_loop_id, metadata_json, created_at,
           updated_at, completed_at
    FROM path_steps
"""

_LEARNING_SUMMARY_SELECT = """
    SELECT summary_id, path_step_id, path_id, run_id, summary_type, what_done,
           why_it_matters, how_it_was_done, knowledge, human_takeaway,
           created_by_elephant_id, metadata_json, created_at
    FROM learning_summaries
"""

_UNDERSTANDING_CHECK_SELECT = """
    SELECT check_id, path_step_id, summary_id, status, checked_by, checked_at,
           note, metadata_json, created_at, updated_at
    FROM understanding_checks
"""
