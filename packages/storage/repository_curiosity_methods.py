"""Repository methods for Fact / OpenQuestion / Diary tables."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Sequence

from packages.contracts import DiaryEntry, Fact, OpenQuestion

from .repository_support import (
    _iso,
    _json_mapping,
    canonical_personal_model_id,
)


def _json_list_text(values: Sequence[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


def _parse_json_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if isinstance(data, list):
        return tuple(str(item) for item in data)
    return ()


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _parse_mapping(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    return {}


# -----------------------------------------------------------------------------
# Fact
# -----------------------------------------------------------------------------


def upsert_personal_model_fact(self, fact: Fact) -> None:
    with self.connection() as connection:
        connection.execute(
            """
            INSERT INTO personal_model_facts (
                fact_id, personal_model_id, lens, text, confidence,
                committed_at, source, source_episode_ids,
                status, supersedes_fact_id, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fact_id) DO UPDATE SET
                personal_model_id = excluded.personal_model_id,
                lens = excluded.lens,
                text = excluded.text,
                confidence = excluded.confidence,
                committed_at = excluded.committed_at,
                source = excluded.source,
                source_episode_ids = excluded.source_episode_ids,
                status = excluded.status,
                supersedes_fact_id = excluded.supersedes_fact_id,
                metadata = excluded.metadata
            """,
            (
                fact.fact_id,
                canonical_personal_model_id(fact.personal_model_id),
                fact.lens,
                fact.text,
                float(fact.confidence),
                _iso(fact.committed_at),
                fact.source,
                _json_list_text(fact.source_episode_ids),
                fact.status,
                fact.supersedes_fact_id,
                _json_mapping(dict(fact.metadata)),
            ),
        )
        connection.commit()


def _row_has(row, key: str) -> bool:
    try:
        _ = row[key]
        return True
    except (IndexError, KeyError):
        return False


def _fact_from_row(row) -> Fact:
    return Fact(
        fact_id=row["fact_id"],
        personal_model_id=row["personal_model_id"],
        lens=row["lens"],
        text=row["text"],
        confidence=float(row["confidence"]),
        committed_at=_parse_datetime(row["committed_at"]) or datetime.now(timezone.utc),
        source=row["source"],
        source_episode_ids=_parse_json_list(row["source_episode_ids"]),
        status=row["status"],
        supersedes_fact_id=row["supersedes_fact_id"],
        metadata=_parse_mapping(row["metadata"]),
        last_accessed_at=_parse_datetime(row["last_accessed_at"]) if _row_has(row, "last_accessed_at") else None,
        access_count=int(row["access_count"] or 0) if _row_has(row, "access_count") else 0,
    )


def touch_fact_access(self, fact_ids: tuple[str, ...], *, now: datetime | None = None) -> None:
    """Update last_accessed_at and increment access_count for retrieved facts."""
    if not fact_ids:
        return
    effective_now = _iso(now or datetime.now(timezone.utc))
    with self.connection() as connection:
        for fact_id in fact_ids:
            connection.execute(
                """
                UPDATE personal_model_facts
                SET last_accessed_at = ?, access_count = COALESCE(access_count, 0) + 1
                WHERE fact_id = ?
                """,
                (effective_now, fact_id),
            )
        connection.commit()


def list_personal_model_facts(
    self,
    *,
    personal_model_id: str,
    lens: str | None = None,
    status: str | Sequence[str] = "active",
) -> tuple[Fact, ...]:
    clauses = ["personal_model_id = ?"]
    parameters: list = [canonical_personal_model_id(personal_model_id)]
    if lens is not None:
        clauses.append("lens = ?")
        parameters.append(lens)
    if status is not None:
        if isinstance(status, str):
            clauses.append("status = ?")
            parameters.append(status)
        else:
            placeholders = ",".join(["?"] * len(status))
            clauses.append(f"status IN ({placeholders})")
            parameters.extend(list(status))
    where_sql = " WHERE " + " AND ".join(clauses)
    with self.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM personal_model_facts" + where_sql + " ORDER BY lens ASC, confidence DESC, committed_at DESC",
            tuple(parameters),
        ).fetchall()
    return tuple(_fact_from_row(row) for row in rows)


# -----------------------------------------------------------------------------
# OpenQuestion
# -----------------------------------------------------------------------------


def upsert_open_question(self, question: OpenQuestion) -> None:
    with self.connection() as connection:
        connection.execute(
            """
            INSERT INTO personal_model_open_questions (
                question_id, personal_model_id, lens, sub_lens, text,
                rationale, priority, sensitivity, source, created_at, status,
                asked_count, last_asked_at, last_asked_surface,
                user_response_episode_ids, dismissed_reason,
                generated_fact_ids, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(question_id) DO UPDATE SET
                personal_model_id = excluded.personal_model_id,
                lens = excluded.lens,
                sub_lens = excluded.sub_lens,
                text = excluded.text,
                rationale = excluded.rationale,
                priority = excluded.priority,
                sensitivity = excluded.sensitivity,
                source = excluded.source,
                created_at = excluded.created_at,
                status = excluded.status,
                asked_count = excluded.asked_count,
                last_asked_at = excluded.last_asked_at,
                last_asked_surface = excluded.last_asked_surface,
                user_response_episode_ids = excluded.user_response_episode_ids,
                dismissed_reason = excluded.dismissed_reason,
                generated_fact_ids = excluded.generated_fact_ids,
                metadata = excluded.metadata
            """,
            (
                question.question_id,
                canonical_personal_model_id(question.personal_model_id),
                question.lens,
                question.sub_lens,
                question.text,
                question.rationale,
                float(question.priority),
                question.sensitivity,
                question.source,
                _iso(question.created_at),
                question.status,
                int(question.asked_count),
                _iso(question.last_asked_at) if question.last_asked_at is not None else None,
                question.last_asked_surface,
                _json_list_text(question.user_response_episode_ids),
                question.dismissed_reason,
                _json_list_text(question.generated_fact_ids),
                _json_mapping(dict(question.metadata)),
            ),
        )
        connection.commit()


def _open_question_from_row(row) -> OpenQuestion:
    return OpenQuestion(
        question_id=row["question_id"],
        personal_model_id=row["personal_model_id"],
        lens=row["lens"],
        sub_lens=row["sub_lens"],
        text=row["text"],
        rationale=row["rationale"],
        priority=float(row["priority"]),
        sensitivity=row["sensitivity"],
        source=row["source"],
        created_at=_parse_datetime(row["created_at"]) or datetime.now(timezone.utc),
        status=row["status"],
        asked_count=int(row["asked_count"]),
        last_asked_at=_parse_datetime(row["last_asked_at"]),
        last_asked_surface=row["last_asked_surface"],
        user_response_episode_ids=_parse_json_list(row["user_response_episode_ids"]),
        dismissed_reason=row["dismissed_reason"],
        generated_fact_ids=_parse_json_list(row["generated_fact_ids"]),
        metadata=_parse_mapping(row["metadata"]),
    )


def list_open_questions(
    self,
    *,
    personal_model_id: str,
    status: str | Sequence[str] = "open",
    lens: str | None = None,
    sub_lens: str | None = None,
    limit: int | None = None,
) -> tuple[OpenQuestion, ...]:
    clauses = ["personal_model_id = ?"]
    parameters: list = [canonical_personal_model_id(personal_model_id)]
    if status is not None:
        if isinstance(status, str):
            clauses.append("status = ?")
            parameters.append(status)
        else:
            placeholders = ",".join(["?"] * len(status))
            clauses.append(f"status IN ({placeholders})")
            parameters.extend(list(status))
    if lens is not None:
        clauses.append("lens = ?")
        parameters.append(lens)
    if sub_lens is not None:
        clauses.append("sub_lens = ?")
        parameters.append(sub_lens)
    where_sql = " WHERE " + " AND ".join(clauses)
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    with self.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM personal_model_open_questions"
            + where_sql
            + " ORDER BY priority DESC, created_at ASC"
            + limit_sql,
            tuple(parameters),
        ).fetchall()
    return tuple(_open_question_from_row(row) for row in rows)


def mark_open_question(
    self,
    *,
    question_id: str,
    status: str,
    surface: str | None = None,
    now: datetime | None = None,
    dismissed_reason: str | None = None,
    generated_fact_ids: Sequence[str] | None = None,
    user_response_episode_id: str | None = None,
) -> None:
    timestamp = now or datetime.now(timezone.utc)
    with self.connection() as connection:
        row = connection.execute(
            "SELECT * FROM personal_model_open_questions WHERE question_id = ?",
            (question_id,),
        ).fetchone()
        if row is None:
            return
        existing = _open_question_from_row(row)
        new_asked_count = existing.asked_count + (1 if status == "asked" else 0)
        new_last_asked_at = timestamp if status == "asked" else existing.last_asked_at
        new_last_asked_surface = surface if status == "asked" else existing.last_asked_surface
        new_response_ids = list(existing.user_response_episode_ids)
        if user_response_episode_id and user_response_episode_id not in new_response_ids:
            new_response_ids.append(user_response_episode_id)
        new_generated_fact_ids = list(generated_fact_ids or existing.generated_fact_ids)
        connection.execute(
            """
            UPDATE personal_model_open_questions
            SET status = ?,
                asked_count = ?,
                last_asked_at = ?,
                last_asked_surface = ?,
                user_response_episode_ids = ?,
                dismissed_reason = ?,
                generated_fact_ids = ?
            WHERE question_id = ?
            """,
            (
                status,
                new_asked_count,
                _iso(new_last_asked_at) if new_last_asked_at is not None else None,
                new_last_asked_surface,
                _json_list_text(new_response_ids),
                dismissed_reason or existing.dismissed_reason,
                _json_list_text(new_generated_fact_ids),
                question_id,
            ),
        )
        connection.commit()


def delete_open_question(self, *, question_id: str) -> None:
    with self.connection() as connection:
        connection.execute(
            "DELETE FROM personal_model_open_questions WHERE question_id = ?",
            (question_id,),
        )
        connection.commit()


# --- Diary entries ---


def _diary_entry_from_row(row) -> DiaryEntry:
    return DiaryEntry(
        entry_id=row["entry_id"],
        personal_model_id=row["personal_model_id"],
        entry_date=row["entry_date"],
        content=row["content"],
        generated_at=_parse_datetime(row["generated_at"]) or datetime.now(timezone.utc),
        source_episode_ids=_parse_json_list(row["source_episode_ids"] if _row_has(row, "source_episode_ids") else None),
        metadata=_parse_mapping(row["metadata"]),
    )


def upsert_diary_entry(self, entry: DiaryEntry) -> None:
    with self.connection() as connection:
        connection.execute(
            """
            INSERT INTO diary_entries (
                entry_id, personal_model_id, entry_date, content,
                generated_at, source_episode_ids, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(personal_model_id, entry_date) DO UPDATE SET
                entry_id = excluded.entry_id,
                content = excluded.content,
                generated_at = excluded.generated_at,
                source_episode_ids = excluded.source_episode_ids,
                metadata = excluded.metadata
            """,
            (
                entry.entry_id,
                canonical_personal_model_id(entry.personal_model_id),
                entry.entry_date,
                entry.content,
                _iso(entry.generated_at),
                _json_list_text(entry.source_episode_ids),
                _json_mapping(dict(entry.metadata)) if entry.metadata else None,
            ),
        )
        connection.commit()


def load_diary_entry(self, *, personal_model_id: str, entry_date: str) -> DiaryEntry | None:
    with self.connection() as connection:
        cursor = connection.execute(
            "SELECT * FROM diary_entries WHERE personal_model_id = ? AND entry_date = ?",
            (canonical_personal_model_id(personal_model_id), entry_date),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return _diary_entry_from_row(row)


def delete_diary_entry(self, *, personal_model_id: str, entry_date: str) -> bool:
    with self.connection() as connection:
        cursor = connection.execute(
            "DELETE FROM diary_entries WHERE personal_model_id = ? AND entry_date = ?",
            (canonical_personal_model_id(personal_model_id), entry_date),
        )
        connection.commit()
    return int(cursor.rowcount or 0) > 0


def list_diary_entries(
    self,
    *,
    personal_model_id: str,
    limit: int = 30,
    before_date: str | None = None,
) -> tuple[DiaryEntry, ...]:
    pm_id = canonical_personal_model_id(personal_model_id)
    if before_date:
        query = "SELECT * FROM diary_entries WHERE personal_model_id = ? AND entry_date < ? ORDER BY entry_date DESC LIMIT ?"
        params: tuple = (pm_id, before_date, limit)
    else:
        query = "SELECT * FROM diary_entries WHERE personal_model_id = ? ORDER BY entry_date DESC LIMIT ?"
        params = (pm_id, limit)
    with self.connection() as connection:
        cursor = connection.execute(query, params)
        rows = cursor.fetchall()
    return tuple(_diary_entry_from_row(row) for row in rows)
