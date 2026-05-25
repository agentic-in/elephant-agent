"""Learning job and growth repository methods."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence
from uuid import uuid4

from packages.contracts.runtime import LearningJob, PersonalModelGrowthState

from .repository_support import (
    _iso,
    _json_dict_text,
    _json_mapping,
    _learning_job_from_row,
    canonical_personal_model_id,
)
from .repository_system_methods import _iso_optional_datetime, _parse_optional_datetime


def upsert_personal_model_growth(
    self,
    state: PersonalModelGrowthState,
) -> None:
    canonical_id = canonical_personal_model_id(state.profile_id)
    now = datetime.now(timezone.utc)
    with self.connection() as connection:
        connection.execute(
            """INSERT INTO personal_model_growth (
                profile_id, growth_score, total_dialogues, total_tokens,
                total_experiences, promoted_experiences, active_days, streak_days,
                first_dialogue_at, last_dialogue_at, last_active_day,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                growth_score = excluded.growth_score,
                total_dialogues = excluded.total_dialogues,
                total_tokens = excluded.total_tokens,
                total_experiences = excluded.total_experiences,
                promoted_experiences = excluded.promoted_experiences,
                active_days = excluded.active_days,
                streak_days = excluded.streak_days,
                first_dialogue_at = excluded.first_dialogue_at,
                last_dialogue_at = excluded.last_dialogue_at,
                last_active_day = excluded.last_active_day,
                updated_at = excluded.updated_at
            """,
            (
                canonical_id,
                state.growth_score,
                state.total_dialogues,
                state.total_tokens,
                state.total_experiences,
                state.promoted_experiences,
                state.active_days,
                state.streak_days,
                _iso_optional_datetime(state.first_dialogue_at),
                _iso_optional_datetime(state.last_dialogue_at),
                state.last_active_day,
                _iso_optional_datetime(state.created_at) or _iso(now),
                _iso_optional_datetime(state.updated_at) or _iso(now),
            ),
        )
        connection.commit()


def load_personal_model_growth(
    self,
    profile_id: str,
) -> PersonalModelGrowthState | None:
    canonical_id = canonical_personal_model_id(profile_id)
    with self.connection() as connection:
        row = connection.execute(
            "SELECT * FROM personal_model_growth WHERE profile_id = ?",
            (canonical_id,),
        ).fetchone()
    if row is None:
        return None
    return PersonalModelGrowthState(
        profile_id=str(row[0]),
        growth_score=int(row[1]),
        total_dialogues=int(row[2]),
        total_tokens=int(row[3]),
        total_experiences=int(row[4]),
        promoted_experiences=int(row[5]),
        active_days=int(row[6]),
        streak_days=int(row[7]),
        first_dialogue_at=_parse_optional_datetime(row[8]),
        last_dialogue_at=_parse_optional_datetime(row[9]),
        last_active_day=row[10] if row[10] is not None else None,
        created_at=_parse_optional_datetime(row[11]),
        updated_at=_parse_optional_datetime(row[12]),
    )


def enqueue_learning_job(
    self,
    *,
    job_type: str,
    trigger: str,
    personal_model_id: str,
    state_id: str,
    episode_id: str,
    loop_id: str | None = None,
    summary: str = "",
    metadata: Mapping[str, str] | None = None,
    available_at: datetime | None = None,
    max_attempts: int = 3,
    force_new: bool = False,
) -> LearningJob:
    canonical_id = canonical_personal_model_id(personal_model_id)
    existing = None if force_new else load_learning_job_for_episode(self, job_type=job_type, episode_id=episode_id)
    if existing is not None and existing.status in {"queued", "running", "completed"}:
        return existing
    created_at = datetime.now(timezone.utc)
    job_id = existing.job_id if existing is not None else f"learning-job:{uuid4().hex}"
    queued = LearningJob(
        job_id=job_id,
        job_type=job_type,
        trigger=trigger,
        status="queued",
        personal_model_id=canonical_id,
        state_id=state_id,
        episode_id=episode_id,
        loop_id=loop_id,
        summary=summary,
        progress_stage="queued",
        progress_detail="queued for background learning",
        attempt_count=existing.attempt_count if existing is not None else 0,
        max_attempts=max(1, max_attempts),
        available_at=available_at or created_at,
        created_at=existing.created_at if existing is not None else created_at,
        started_at=None,
        finished_at=None,
        worker_id=None,
        last_error="",
        metadata=dict(metadata or (existing.metadata if existing is not None else {})),
        result_json=dict(existing.result_json) if existing is not None else {},
    )
    with self.connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO learning_jobs (
                job_id,
                job_type,
                trigger,
                status,
                personal_model_id,
                state_id,
                episode_id,
                loop_id,
                summary,
                progress_stage,
                progress_detail,
                attempt_count,
                max_attempts,
                available_at,
                created_at,
                started_at,
                finished_at,
                worker_id,
                last_error,
                metadata_json,
                result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                queued.job_id,
                queued.job_type,
                queued.trigger,
                queued.status,
                queued.personal_model_id,
                queued.state_id,
                queued.episode_id,
                queued.loop_id or "",
                queued.summary,
                queued.progress_stage,
                queued.progress_detail,
                queued.attempt_count,
                queued.max_attempts,
                _iso(queued.available_at),
                _iso(queued.created_at),
                _iso_optional_datetime(queued.started_at),
                _iso_optional_datetime(queued.finished_at),
                queued.worker_id or "",
                queued.last_error,
                _json_mapping(dict(queued.metadata)),
                _json_dict_text(dict(queued.result_json)),
            ),
        )
        connection.commit()
    loaded = self.load_learning_job(queued.job_id)
    if loaded is None:
        raise RuntimeError("learning job was not persisted")
    return loaded


def load_learning_job(self, job_id: str) -> LearningJob | None:
    with self.connection() as connection:
        row = connection.execute(
            "SELECT * FROM learning_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    return _learning_job_from_row(row)



def load_learning_job_for_episode(self, *, job_type: str, episode_id: str) -> LearningJob | None:
    with self.connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM learning_jobs
            WHERE job_type = ? AND episode_id = ?
            ORDER BY created_at DESC, job_id DESC
            LIMIT 1
            """,
            (job_type, episode_id),
        ).fetchone()
    if row is None:
        return None
    return _learning_job_from_row(row)



def list_learning_jobs(
    self,
    *,
    statuses: tuple[str, ...] = (),
    state_id: str | None = None,
    personal_model_id: str | None = None,
    episode_id: str | None = None,
    limit: int | None = None,
) -> tuple[LearningJob, ...]:
    clauses: list[str] = []
    parameters: list[object] = []
    if statuses:
        placeholders = ", ".join("?" for _ in statuses)
        clauses.append(f"status IN ({placeholders})")
        parameters.extend(statuses)
    if state_id is not None:
        clauses.append("state_id = ?")
        parameters.append(state_id)
    if personal_model_id is not None:
        clauses.append("personal_model_id = ?")
        parameters.append(canonical_personal_model_id(personal_model_id))
    if episode_id is not None:
        clauses.append("episode_id = ?")
        parameters.append(episode_id)
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    limit_sql = ""
    if limit is not None and limit > 0:
        limit_sql = " LIMIT ?"
        parameters.append(limit)
    with self.connection() as connection:
        rows: Sequence[object] = connection.execute(
            "SELECT * FROM learning_jobs"
            + (" " + where_sql if where_sql else "")
            + " ORDER BY created_at DESC, job_id DESC" + limit_sql,
            tuple(parameters),
        ).fetchall()
    return tuple(_learning_job_from_row(row) for row in rows)



def claim_learning_job(self, *, worker_id: str, now: datetime | None = None) -> LearningJob | None:
    claimed_at = now or datetime.now(timezone.utc)
    with self.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT *
            FROM learning_jobs
            WHERE status = 'queued'
              AND available_at <= ?
            ORDER BY available_at ASC, created_at ASC, job_id ASC
            LIMIT 1
            """,
            (_iso(claimed_at),),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        connection.execute(
            """
            UPDATE learning_jobs
            SET status = 'running',
                progress_stage = 'starting',
                progress_detail = 'worker claimed job',
                attempt_count = attempt_count + 1,
                started_at = ?,
                finished_at = NULL,
                worker_id = ?,
                last_error = ''
            WHERE job_id = ?
            """,
            (_iso(claimed_at), worker_id, str(row["job_id"])),
        )
        connection.commit()
    return self.load_learning_job(str(row["job_id"]))



def update_learning_job_progress(
    self,
    job_id: str,
    *,
    worker_id: str,
    progress_stage: str,
    progress_detail: str = "",
) -> LearningJob:
    with self.connection() as connection:
        connection.execute(
            """
            UPDATE learning_jobs
            SET progress_stage = ?,
                progress_detail = ?,
                worker_id = ?
            WHERE job_id = ?
            """,
            (progress_stage, progress_detail, worker_id, job_id),
        )
        connection.commit()
    loaded = self.load_learning_job(job_id)
    if loaded is None:
        raise KeyError(job_id)
    return loaded



def write_learning_job_result(
    self,
    job_id: str,
    result: Mapping[str, object],
    *,
    worker_id: str = "learning-result",
    progress_detail: str = "learning result written",
    overwrite: bool = False,
) -> LearningJob:
    existing = self.load_learning_job(job_id)
    if existing is None:
        raise KeyError(job_id)
    if existing.result_json and not overwrite:
        raise ValueError(f"learning result already written for job: {job_id}")
    payload = dict(result)
    with self.connection() as connection:
        connection.execute(
            """
            UPDATE learning_jobs
            SET result_json = ?,
                progress_stage = 'result_written',
                progress_detail = ?,
                worker_id = ?
            WHERE job_id = ?
            """,
            (_json_dict_text(payload), progress_detail, worker_id, job_id),
        )
        connection.commit()
    loaded = self.load_learning_job(job_id)
    if loaded is None:
        raise KeyError(job_id)
    return loaded



def complete_learning_job(
    self,
    job_id: str,
    *,
    worker_id: str,
    finished_at: datetime | None = None,
    progress_detail: str = "background learning completed",
) -> LearningJob:
    completed_at = finished_at or datetime.now(timezone.utc)
    with self.connection() as connection:
        connection.execute(
            """
            UPDATE learning_jobs
            SET status = 'completed',
                progress_stage = 'completed',
                progress_detail = ?,
                finished_at = ?,
                worker_id = ?
            WHERE job_id = ?
            """,
            (progress_detail, _iso(completed_at), worker_id, job_id),
        )
        connection.commit()
    loaded = self.load_learning_job(job_id)
    if loaded is None:
        raise KeyError(job_id)
    return loaded



def fail_learning_job(
    self,
    job_id: str,
    *,
    worker_id: str,
    error: str,
    finished_at: datetime | None = None,
    retry_delay_seconds: int = 0,
) -> LearningJob:
    failed_at = finished_at or datetime.now(timezone.utc)
    existing = self.load_learning_job(job_id)
    if existing is None:
        raise KeyError(job_id)
    will_retry = existing.attempt_count < existing.max_attempts
    next_status = "queued" if will_retry else "failed"
    next_stage = "retrying" if will_retry else "failed"
    next_detail = "retry scheduled" if will_retry else "background learning failed"
    available_at = failed_at if retry_delay_seconds <= 0 else failed_at.replace(microsecond=0) + timedelta(seconds=retry_delay_seconds)
    with self.connection() as connection:
        connection.execute(
            """
            UPDATE learning_jobs
            SET status = ?,
                progress_stage = ?,
                progress_detail = ?,
                available_at = ?,
                finished_at = ?,
                worker_id = ?,
                last_error = ?
            WHERE job_id = ?
            """,
            (
                next_status,
                next_stage,
                next_detail,
                _iso(available_at),
                _iso(failed_at) if not will_retry else None,
                worker_id,
                error.strip(),
                job_id,
            ),
        )
        connection.commit()
    loaded = self.load_learning_job(job_id)
    if loaded is None:
        raise KeyError(job_id)
    return loaded



