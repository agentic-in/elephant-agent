"""Repository methods for Path learning summaries and checks."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Sequence
from uuid import uuid4

from packages.contracts.paths import (
    LearningSummaryRecord,
    UnderstandingCheckRecord,
    path_step_status_after_learning_summary,
    path_step_status_after_understanding_check,
)

from .repository_support import (
    _iso,
    _json_mapping,
    _learning_summary_from_row,
    _understanding_check_from_row,
)


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
    if run_id:
        try:
            self.update_path_step_run(
                run_id,
                status="completed",
                progress_stage="completed",
                progress_detail="Learning summary attached",
                progress_current=4,
                progress_total=4,
            )
        except KeyError:
            pass
    next_status = path_step_status_after_learning_summary(step.status)
    if next_status != step.status:
        self.upsert_path_step(replace(step, status=next_status))
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
    step = self.load_path_step(summary.path_step_id)
    if step is not None:
        next_status = path_step_status_after_understanding_check(step.status, loaded.status)
        if next_status != step.status:
            self.upsert_path_step(replace(step, status=next_status))
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
