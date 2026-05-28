"""Repository methods for Path step run queue records."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Sequence
from uuid import uuid4

from packages.contracts.paths import PathStepRunRecord, path_step_status_after_run

from .repository_support import (
    _iso,
    _json_mapping,
    _path_step_run_from_row,
    canonical_personal_model_id,
)


def create_path_step_run(
    self,
    *,
    path_step_id: str,
    status: str = "queued",
    attempt: int | None = None,
    max_attempts: int = 3,
    parent_run_id: str = "",
    assignee_elephant_id: str = "",
    runtime_id: str = "",
    claim_token: str = "",
    session_id: str = "",
    work_dir: str = "",
    progress_stage: str = "",
    progress_detail: str = "",
    progress_current: int = 0,
    progress_total: int = 0,
    failure_reason: str = "",
    metadata: dict[str, str] | None = None,
    run_id: str | None = None,
) -> PathStepRunRecord:
    step = self.load_path_step(path_step_id)
    if step is None:
        raise KeyError(path_step_id)
    if attempt is None:
        prior = self.list_path_step_runs(path_step_id=path_step_id)
        attempt = max((run.attempt for run in prior), default=0) + 1
    resolved_assignee = assignee_elephant_id or step.assignee_elephant_id
    record = PathStepRunRecord(
        run_id=run_id or f"path-step-run-{uuid4().hex}",
        path_step_id=path_step_id,
        path_id=step.path_id,
        personal_model_id=step.personal_model_id,
        status=status,
        attempt=attempt,
        max_attempts=max_attempts,
        parent_run_id=parent_run_id,
        assignee_elephant_id=resolved_assignee,
        runtime_id=runtime_id,
        claim_token=claim_token,
        session_id=session_id,
        work_dir=work_dir,
        progress_stage=progress_stage,
        progress_detail=progress_detail,
        progress_current=progress_current,
        progress_total=progress_total,
        failure_reason=failure_reason,
        metadata=metadata or {},
    )
    self.upsert_path_step_run(record)
    loaded = self.load_path_step_run(record.run_id)
    if loaded is None:
        raise RuntimeError("Path step run was not persisted")
    return loaded


def upsert_path_step_run(self, record: PathStepRunRecord, *, updated_at: datetime | None = None) -> None:
    timestamp = _iso(updated_at)
    created_at = _iso(record.created_at) if record.created_at is not None else timestamp
    started_at = _iso(record.started_at) if record.started_at is not None else None
    heartbeat_at = _iso(record.heartbeat_at) if record.heartbeat_at is not None else None
    lease_expires_at = _iso(record.lease_expires_at) if record.lease_expires_at is not None else None
    finished_at = _iso(record.finished_at) if record.finished_at is not None else None
    if record.status in {"dispatched", "running"} and started_at is None:
        started_at = timestamp
    if record.status in {"queued", "dispatched", "running"} and heartbeat_at is None:
        heartbeat_at = timestamp
    if record.status in {"completed", "failed", "cancelled"} and finished_at is None:
        finished_at = timestamp
    with self.connection() as connection:
        existing = connection.execute(
            "SELECT created_at, started_at FROM path_step_runs WHERE run_id = ?",
            (record.run_id,),
        ).fetchone()
        if existing is not None:
            created_at = str(existing["created_at"])
            if started_at is None and existing["started_at"] is not None:
                started_at = str(existing["started_at"])
        connection.execute(
            """
            INSERT INTO path_step_runs (
                run_id,
                path_step_id,
                path_id,
                personal_model_id,
                status,
                attempt,
                max_attempts,
                parent_run_id,
                assignee_elephant_id,
                runtime_id,
                claim_token,
                session_id,
                work_dir,
                progress_stage,
                progress_detail,
                progress_current,
                progress_total,
                failure_reason,
                metadata_json,
                created_at,
                started_at,
                heartbeat_at,
                lease_expires_at,
                finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                path_step_id = excluded.path_step_id,
                path_id = excluded.path_id,
                personal_model_id = excluded.personal_model_id,
                status = excluded.status,
                attempt = excluded.attempt,
                max_attempts = excluded.max_attempts,
                parent_run_id = excluded.parent_run_id,
                assignee_elephant_id = excluded.assignee_elephant_id,
                runtime_id = excluded.runtime_id,
                claim_token = excluded.claim_token,
                session_id = excluded.session_id,
                work_dir = excluded.work_dir,
                progress_stage = excluded.progress_stage,
                progress_detail = excluded.progress_detail,
                progress_current = excluded.progress_current,
                progress_total = excluded.progress_total,
                failure_reason = excluded.failure_reason,
                metadata_json = excluded.metadata_json,
                started_at = COALESCE(path_step_runs.started_at, excluded.started_at),
                heartbeat_at = excluded.heartbeat_at,
                lease_expires_at = excluded.lease_expires_at,
                finished_at = excluded.finished_at
            """,
            (
                record.run_id,
                record.path_step_id,
                record.path_id,
                canonical_personal_model_id(record.personal_model_id),
                record.status,
                int(record.attempt),
                int(record.max_attempts),
                record.parent_run_id,
                record.assignee_elephant_id,
                record.runtime_id,
                record.claim_token,
                record.session_id,
                record.work_dir,
                record.progress_stage,
                record.progress_detail,
                int(record.progress_current),
                int(record.progress_total),
                record.failure_reason,
                _json_mapping(dict(record.metadata)),
                created_at,
                started_at,
                heartbeat_at,
                lease_expires_at,
                finished_at,
            ),
        )
        connection.execute(
            "UPDATE paths SET updated_at = ? WHERE path_id = ?",
            (timestamp, record.path_id),
        )
        connection.commit()
    _sync_step_status_for_run(self, record)


def load_path_step_run(self, run_id: str) -> PathStepRunRecord | None:
    with self.connection() as connection:
        row = connection.execute(_PATH_STEP_RUN_SELECT + " WHERE run_id = ?", (run_id,)).fetchone()
    return _path_step_run_from_row(row) if row is not None else None


def list_path_step_runs(
    self,
    *,
    path_step_id: str | None = None,
    path_id: str | None = None,
    status: str | tuple[str, ...] | None = None,
    runtime_id: str | None = None,
    limit: int | None = None,
) -> tuple[PathStepRunRecord, ...]:
    clauses: list[str] = []
    params: list[object] = []
    if path_step_id:
        clauses.append("path_step_id = ?")
        params.append(path_step_id)
    if path_id:
        clauses.append("path_id = ?")
        params.append(path_id)
    if runtime_id:
        clauses.append("runtime_id = ?")
        params.append(runtime_id)
    if status:
        statuses = (status,) if isinstance(status, str) else tuple(status)
        placeholders = ", ".join("?" for _ in statuses)
        clauses.append(f"status IN ({placeholders})")
        params.extend(statuses)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = _PATH_STEP_RUN_SELECT + where + " ORDER BY created_at DESC, run_id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))
    with self.connection() as connection:
        rows: Sequence[object] = connection.execute(sql, tuple(params)).fetchall()
    return tuple(_path_step_run_from_row(row) for row in rows)


def update_path_step_run(
    self,
    run_id: str,
    *,
    status: str | None = None,
    parent_run_id: str | None = None,
    progress_stage: str | None = None,
    progress_detail: str | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
    failure_reason: str | None = None,
    runtime_id: str | None = None,
    claim_token: str | None = None,
    session_id: str | None = None,
    work_dir: str | None = None,
    assignee_elephant_id: str | None = None,
    heartbeat_at: datetime | None = None,
    lease_expires_at: datetime | None = None,
    metadata: dict[str, str] | None = None,
) -> PathStepRunRecord:
    existing = self.load_path_step_run(run_id)
    if existing is None:
        raise KeyError(run_id)
    next_metadata = dict(existing.metadata)
    if metadata:
        next_metadata.update({str(key): str(value) for key, value in metadata.items()})
    next_status = status or existing.status
    next_lease_expires_at = lease_expires_at if lease_expires_at is not None else existing.lease_expires_at
    if next_status in {"completed", "failed", "cancelled"} and lease_expires_at is None:
        next_lease_expires_at = None
    updated = replace(
        existing,
        status=next_status,
        parent_run_id=parent_run_id if parent_run_id is not None else existing.parent_run_id,
        progress_stage=progress_stage if progress_stage is not None else existing.progress_stage,
        progress_detail=progress_detail if progress_detail is not None else existing.progress_detail,
        progress_current=progress_current if progress_current is not None else existing.progress_current,
        progress_total=progress_total if progress_total is not None else existing.progress_total,
        failure_reason=failure_reason if failure_reason is not None else existing.failure_reason,
        runtime_id=runtime_id if runtime_id is not None else existing.runtime_id,
        claim_token=claim_token if claim_token is not None else existing.claim_token,
        session_id=session_id if session_id is not None else existing.session_id,
        work_dir=work_dir if work_dir is not None else existing.work_dir,
        assignee_elephant_id=(
            assignee_elephant_id if assignee_elephant_id is not None else existing.assignee_elephant_id
        ),
        heartbeat_at=heartbeat_at if heartbeat_at is not None else existing.heartbeat_at,
        lease_expires_at=next_lease_expires_at,
        metadata=next_metadata,
    )
    self.upsert_path_step_run(updated)
    loaded = self.load_path_step_run(run_id)
    if loaded is None:
        raise RuntimeError("Path step run was not persisted")
    return loaded


def retry_path_step_run(
    self,
    run_id: str,
    *,
    reason: str = "retry",
    run_id_override: str | None = None,
) -> PathStepRunRecord:
    existing = self.load_path_step_run(run_id)
    if existing is None:
        raise KeyError(run_id)
    if existing.attempt >= existing.max_attempts:
        raise RuntimeError("path step run retry budget exhausted")
    metadata = dict(existing.metadata)
    metadata["retry_of"] = existing.run_id
    metadata["retry_reason"] = reason
    resume_unsafe = existing.failure_reason in {"codex_semantic_inactivity", "agent_fallback_message"}
    return self.create_path_step_run(
        path_step_id=existing.path_step_id,
        status="queued",
        attempt=existing.attempt + 1,
        max_attempts=existing.max_attempts,
        parent_run_id=existing.run_id,
        assignee_elephant_id=existing.assignee_elephant_id,
        runtime_id=existing.runtime_id,
        session_id="" if resume_unsafe else existing.session_id,
        work_dir="" if resume_unsafe else existing.work_dir,
        metadata=metadata,
        run_id=run_id_override,
    )


def claim_path_step_run(
    self,
    *,
    runtime_id: str,
    assignee_elephant_id: str = "",
    lease_seconds: int = 600,
    claim_token: str | None = None,
) -> PathStepRunRecord | None:
    worker_id = str(runtime_id or "").strip() or "path-runner"
    token = str(claim_token or f"path-run-claim-{uuid4().hex}")
    now = datetime.now(timezone.utc)
    now_text = _iso(now)
    lease_text = _iso(now + timedelta(seconds=max(1, int(lease_seconds))))
    assignee = str(assignee_elephant_id or "").strip()
    assignee_clause = ""
    if assignee:
        assignee_clause = "AND (candidate.assignee_elephant_id = ? OR candidate.assignee_elephant_id = '')"
    sql = f"""
        UPDATE path_step_runs
        SET status = 'dispatched',
            runtime_id = ?,
            claim_token = ?,
            heartbeat_at = ?,
            lease_expires_at = ?,
            progress_stage = CASE
                WHEN progress_stage = '' THEN 'dispatched'
                ELSE progress_stage
            END,
            progress_detail = CASE
                WHEN progress_detail = '' THEN 'Claimed by baby runtime.'
                ELSE progress_detail
            END
        WHERE run_id = (
            SELECT candidate.run_id
            FROM path_step_runs candidate
            WHERE (
                    candidate.status = 'queued'
                    OR (
                        candidate.status = 'dispatched'
                        AND candidate.started_at IS NULL
                        AND candidate.lease_expires_at IS NOT NULL
                        AND candidate.lease_expires_at < ?
                    )
                )
                {assignee_clause}
                AND NOT EXISTS (
                    SELECT 1
                    FROM path_step_runs active
                    WHERE active.path_step_id = candidate.path_step_id
                      AND active.run_id != candidate.run_id
                      AND active.status IN ('dispatched', 'running')
                )
            ORDER BY candidate.attempt ASC, candidate.created_at ASC, candidate.run_id ASC
            LIMIT 1
        )
        RETURNING run_id
    """
    ordered_params = [worker_id, token, now_text, lease_text, now_text]
    if assignee:
        ordered_params.append(assignee)
    with self.connection() as connection:
        row = connection.execute(sql, tuple(ordered_params)).fetchone()
        connection.commit()
    if row is None:
        return None
    claimed = self.load_path_step_run(str(row["run_id"]))
    if claimed is not None:
        _sync_step_status_for_run(self, claimed)
    return claimed


def start_path_step_run(
    self,
    run_id: str,
    *,
    runtime_id: str,
    claim_token: str = "",
    lease_seconds: int = 600,
) -> PathStepRunRecord:
    existing = self.load_path_step_run(run_id)
    if existing is None:
        raise KeyError(run_id)
    token = str(claim_token or existing.claim_token)
    if existing.status != "dispatched" or existing.runtime_id != runtime_id or (token and existing.claim_token != token):
        raise RuntimeError("path step run is not claim-owned by this runtime")
    now = datetime.now(timezone.utc)
    return self.update_path_step_run(
        run_id,
        status="running",
        progress_stage="running",
        progress_detail="Baby runtime started execution.",
        heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=max(1, int(lease_seconds))),
    )


def heartbeat_path_step_run(
    self,
    run_id: str,
    *,
    runtime_id: str,
    claim_token: str = "",
    lease_seconds: int = 600,
    progress_stage: str | None = None,
    progress_detail: str | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
) -> PathStepRunRecord:
    existing = self.load_path_step_run(run_id)
    if existing is None:
        raise KeyError(run_id)
    token = str(claim_token or existing.claim_token)
    if existing.status not in {"dispatched", "running"} or existing.runtime_id != runtime_id or (token and existing.claim_token != token):
        raise RuntimeError("path step run is not claim-owned by this runtime")
    now = datetime.now(timezone.utc)
    return self.update_path_step_run(
        run_id,
        progress_stage=progress_stage,
        progress_detail=progress_detail,
        progress_current=progress_current,
        progress_total=progress_total,
        heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=max(1, int(lease_seconds))),
    )


def sweep_path_step_runs(
    self,
    *,
    dispatch_timeout_seconds: int = 300,
    running_timeout_seconds: int = 3600,
    queued_ttl_seconds: int = 86400,
    max_per_tick: int = 50,
) -> tuple[PathStepRunRecord, ...]:
    now = datetime.now(timezone.utc)
    dispatch_cutoff = _iso(now - timedelta(seconds=max(1, int(dispatch_timeout_seconds))))
    running_cutoff = _iso(now - timedelta(seconds=max(1, int(running_timeout_seconds))))
    queued_cutoff = _iso(now - timedelta(seconds=max(1, int(queued_ttl_seconds))))
    now_text = _iso(now)
    with self.connection() as connection:
        rows = connection.execute(
            """
            SELECT run_id, failure_reason
            FROM path_step_runs
            WHERE status IN ('queued', 'dispatched', 'running')
              AND (
                (status = 'queued' AND created_at < ?)
                OR (status = 'dispatched' AND (
                    (lease_expires_at IS NOT NULL AND lease_expires_at < ?)
                    OR (heartbeat_at IS NOT NULL AND heartbeat_at < ?)
                ))
                OR (status = 'running' AND (
                    (lease_expires_at IS NOT NULL AND lease_expires_at < ?)
                    OR (heartbeat_at IS NOT NULL AND heartbeat_at < ?)
                ))
              )
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (queued_cutoff, now_text, dispatch_cutoff, now_text, running_cutoff, max(1, int(max_per_tick))),
        ).fetchall()
        run_ids = [str(row["run_id"]) for row in rows]
        for run_id in run_ids:
            connection.execute(
                """
                UPDATE path_step_runs
                SET status = 'failed',
                    finished_at = ?,
                    heartbeat_at = ?,
                    lease_expires_at = NULL,
                    progress_stage = 'failed',
                    progress_detail = CASE
                        WHEN status = 'queued' THEN 'Run expired before a baby runtime claimed it.'
                        ELSE 'Run lease expired before completion.'
                    END,
                    failure_reason = CASE
                        WHEN status = 'queued' THEN 'queued_expired'
                        WHEN status = 'dispatched' THEN 'dispatch_timeout'
                        ELSE 'timeout'
                    END
                WHERE run_id = ?
                  AND status IN ('queued', 'dispatched', 'running')
                """,
                (now_text, now_text, run_id),
            )
        connection.commit()
    failed = tuple(self.load_path_step_run(run_id) for run_id in run_ids)
    records = tuple(run for run in failed if run is not None)
    for record in records:
        _sync_step_status_for_run(self, record)
    return records


def maybe_retry_path_step_run(
    self,
    run_id: str,
    *,
    reason: str = "auto_retry",
    retryable_failure_reasons: tuple[str, ...] = (
        "agent_error",
        "timeout",
        "dispatch_timeout",
        "runtime_recovery",
        "queued_expired",
        "rate_limited",
    ),
) -> PathStepRunRecord | None:
    existing = self.load_path_step_run(run_id)
    if existing is None or existing.status != "failed":
        return None
    if existing.failure_reason not in retryable_failure_reasons:
        return None
    if existing.attempt >= existing.max_attempts:
        return None
    return self.retry_path_step_run(run_id, reason=reason)

_PATH_STEP_RUN_SELECT = """
    SELECT run_id, path_step_id, path_id, personal_model_id, status, attempt,
           max_attempts, parent_run_id, assignee_elephant_id, runtime_id,
           claim_token, session_id, work_dir, progress_stage, progress_detail,
           progress_current, progress_total, failure_reason, metadata_json,
           created_at, started_at, heartbeat_at, lease_expires_at, finished_at
    FROM path_step_runs
"""

def _sync_step_status_for_run(self, run: PathStepRunRecord) -> None:
    step = self.load_path_step(run.path_step_id)
    if step is None:
        return
    next_status = path_step_status_after_run(step.status, run.status)
    if next_status != step.status:
        self.upsert_path_step(replace(step, status=next_status))
