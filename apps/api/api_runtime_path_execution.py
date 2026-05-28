"""Path step run execution helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from threading import Event, Lock, Thread
import time
from typing import Any, Mapping
from uuid import uuid4

from packages.context.epoch_store import FileEpochStore
from packages.context.session_projection import SessionContextEpoch
from packages.contracts.layers import Episode
from packages.contracts.paths import (
    LearningSummaryRecord,
    PathRecord,
    PathStepCommentRecord,
    PathStepRecord,
    PathStepRunRecord,
)
from packages.contracts.runtime import PromptMessage
from packages.operator.local_agent_adapters import run_local_agent_cli
from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID

PATH_STEP_RUNNER_RUNTIME_ID = "api.path-runner"
PATH_STEP_RUNNER_LEASE_SECONDS = 600
PATH_STEP_RUNNER_IDLE_SLEEP_SECONDS = 0.25
PATH_STEP_RUNNER_IDLE_TICKS = 4
PATH_STEP_RUNNER_HEARTBEAT_SECONDS = 30


def _index_learning_summary(self: Any, summary: LearningSummaryRecord) -> None:
    indexer = getattr(self, "semantic_summary_indexer", None)
    index_learning_summary = getattr(indexer, "index_learning_summary", None)
    if not callable(index_learning_summary):
        return
    try:
        step = self.repository.load_path_step(summary.path_step_id)
        path = self.repository.load_path(summary.path_id)
        index_learning_summary(summary, path_step=step, path=path)
    except Exception:
        return


def _dispatch_path_step_runs(
    self,
    method: str,
    step: PathStepRecord,
    parts: tuple[str, ...],
    body: bytes | None,
) -> APIResponse:
    if method == "GET" and not parts:
        runs = self.repository.list_path_step_runs(path_step_id=step.path_step_id)
        return APIResponse(200, {"runs": tuple(_path_step_run_payload(run) for run in runs)})
    if method == "POST" and not parts:
        payload = _read_json_bytes(body)
        run = self.repository.create_path_step_run(
            path_step_id=step.path_step_id,
            status=_payload_text(payload, "status", default="queued"),
            attempt=_payload_optional_int(payload, "attempt"),
            max_attempts=_payload_optional_int(payload, "max_attempts", "maxAttempts", default=3) or 3,
            parent_run_id=_payload_text(payload, "parent_run_id", "parentRunId"),
            assignee_elephant_id=_payload_text(payload, "assignee_elephant_id", "assigneeElephantId"),
            runtime_id=_payload_text(payload, "runtime_id", "runtimeId"),
            claim_token=_payload_text(payload, "claim_token", "claimToken"),
            session_id=_payload_text(payload, "session_id", "sessionId"),
            work_dir=_payload_text(payload, "work_dir", "workDir"),
            progress_stage=_payload_text(payload, "progress_stage", "progressStage"),
            progress_detail=_payload_text(payload, "progress_detail", "progressDetail"),
            progress_current=_payload_optional_int(payload, "progress_current", "progressCurrent", default=0) or 0,
            progress_total=_payload_optional_int(payload, "progress_total", "progressTotal", default=0) or 0,
            failure_reason=_payload_text(payload, "failure_reason", "failureReason"),
            metadata=_payload_mapping(payload.get("metadata")),
            run_id=_payload_text(payload, "run_id", "runId") or None,
        )
        auto_execute = _payload_bool(payload, "auto_execute", "autoExecute")
        if auto_execute:
            _start_path_step_run_executor(self, run.run_id)
        updated_step = self.repository.load_path_step(step.path_step_id) or step
        return APIResponse(
            201,
            {
                "run": _path_step_run_payload(run),
                "step": _path_step_payload(self.repository, updated_step, include_summaries=True),
                "auto_execute": auto_execute,
            },
        )
    if not parts:
        return APIResponse(404, {"error": "not_found"})
    run_id = unquote(parts[0])
    run = self.repository.load_path_step_run(run_id)
    if run is None or run.path_step_id != step.path_step_id:
        raise KeyError(run_id)
    if method == "GET" and len(parts) == 1:
        return APIResponse(200, {"run": _path_step_run_payload(run)})
    if method == "PATCH" and len(parts) == 1:
        payload = _read_json_bytes(body)
        updated = self.repository.update_path_step_run(
            run_id,
            status=_payload_text(payload, "status", default="") or None,
            parent_run_id=_payload_text(payload, "parent_run_id", "parentRunId", default="") if ("parent_run_id" in payload or "parentRunId" in payload) else None,
            progress_stage=_payload_text(payload, "progress_stage", "progressStage", default="") if ("progress_stage" in payload or "progressStage" in payload) else None,
            progress_detail=_payload_text(payload, "progress_detail", "progressDetail", default="") if ("progress_detail" in payload or "progressDetail" in payload) else None,
            progress_current=_payload_optional_int(payload, "progress_current", "progressCurrent"),
            progress_total=_payload_optional_int(payload, "progress_total", "progressTotal"),
            failure_reason=_payload_text(payload, "failure_reason", "failureReason", default="") if ("failure_reason" in payload or "failureReason" in payload) else None,
            runtime_id=_payload_text(payload, "runtime_id", "runtimeId", default="") if ("runtime_id" in payload or "runtimeId" in payload) else None,
            claim_token=_payload_text(payload, "claim_token", "claimToken", default="") if ("claim_token" in payload or "claimToken" in payload) else None,
            session_id=_payload_text(payload, "session_id", "sessionId", default="") if ("session_id" in payload or "sessionId" in payload) else None,
            work_dir=_payload_text(payload, "work_dir", "workDir", default="") if ("work_dir" in payload or "workDir" in payload) else None,
            assignee_elephant_id=_payload_text(payload, "assignee_elephant_id", "assigneeElephantId", default="") if ("assignee_elephant_id" in payload or "assigneeElephantId" in payload) else None,
            metadata=_payload_mapping(payload.get("metadata")) if "metadata" in payload else None,
        )
        updated_step = self.repository.load_path_step(step.path_step_id) or step
        return APIResponse(
            200,
            {
                "run": _path_step_run_payload(updated),
                "step": _path_step_payload(self.repository, updated_step, include_summaries=True),
            },
        )
    if method == "POST" and len(parts) == 2 and parts[1] == "retry":
        payload = _read_json_bytes(body)
        retry = self.repository.retry_path_step_run(
            run_id,
            reason=_payload_text(payload, "reason", default="manual_retry"),
            run_id_override=_payload_text(payload, "run_id", "runId") or None,
        )
        auto_execute = _payload_bool(payload, "auto_execute", "autoExecute")
        if auto_execute:
            _start_path_step_run_executor(self, retry.run_id)
        updated_step = self.repository.load_path_step(step.path_step_id) or step
        return APIResponse(
            201,
            {
                "run": _path_step_run_payload(retry),
                "step": _path_step_payload(self.repository, updated_step, include_summaries=True),
                "auto_execute": auto_execute,
            },
        )
    return APIResponse(404, {"error": "not_found"})


def _dispatch_path_step_comments(
    self,
    method: str,
    step: PathStepRecord,
    parts: tuple[str, ...],
    body: bytes | None,
) -> APIResponse:
    if method == "GET" and not parts:
        comments = self.repository.list_path_step_comments(path_step_id=step.path_step_id, limit=100)
        return APIResponse(200, {"comments": tuple(_path_step_comment_payload(comment) for comment in comments)})
    if method == "POST" and not parts:
        payload = _read_json_bytes(body)
        comment = self.repository.create_path_step_comment(
            path_step_id=step.path_step_id,
            body=_required_payload_text(payload, "body", "content", "text"),
            author_kind=_payload_text(payload, "author_kind", "authorKind", default="user"),
            author_id=_payload_text(payload, "author_id", "authorId", default="user"),
            comment_type=_payload_text(payload, "comment_type", "commentType", default="comment"),
            run_id=_payload_text(payload, "run_id", "runId"),
            parent_comment_id=_payload_text(payload, "parent_comment_id", "parentCommentId"),
            metadata=_payload_mapping(payload.get("metadata")),
            comment_id=_payload_text(payload, "comment_id", "commentId") or None,
        )
        path = self.repository.load_path(step.path_id)
        episode_id = _ensure_path_step_episode(self, step, path)
        _append_path_step_comment_to_episode_history(self, episode_id, comment)
        step = self.repository.load_path_step(step.path_step_id) or step
        auto_run = _payload_bool(payload, "auto_run", "autoRun")
        queued_run: PathStepRunRecord | None = None
        if auto_run and step.status != "dropped":
            if step.status == "done":
                self.repository.upsert_path_step(replace(step, status="moving"))
                step = self.repository.load_path_step(step.path_step_id) or step
            queued_run = self.repository.create_path_step_run(
                path_step_id=step.path_step_id,
                status="queued",
                max_attempts=_payload_optional_int(payload, "max_attempts", "maxAttempts", default=3) or 3,
                assignee_elephant_id=step.assignee_elephant_id,
                metadata={
                    "source": "path_step_comment",
                    "trigger_comment_id": comment.comment_id,
                    "trigger_comment_body": comment.body,
                },
            )
            _start_path_step_run_executor(self, queued_run.run_id)
        updated_step = self.repository.load_path_step(step.path_step_id) or step
        return APIResponse(
            201,
            {
                "comment": _path_step_comment_payload(comment),
                "run": _path_step_run_payload(queued_run),
                "step": _path_step_payload(self.repository, updated_step, include_summaries=True),
                "auto_run": auto_run,
            },
        )
    if not parts:
        return APIResponse(404, {"error": "not_found"})
    comment_id = unquote(parts[0])
    comment = self.repository.load_path_step_comment(comment_id)
    if comment is None or comment.path_step_id != step.path_step_id:
        raise KeyError(comment_id)
    if method == "GET" and len(parts) == 1:
        return APIResponse(200, {"comment": _path_step_comment_payload(comment)})
    return APIResponse(404, {"error": "not_found"})


def _start_path_step_run_executor(self: Any, _run_id: str = "") -> None:
    _ensure_path_step_run_worker(self)


def _ensure_path_step_run_worker(self: Any) -> None:
    lock = getattr(self, "_path_step_run_worker_lock", None)
    if lock is None:
        lock = Lock()
        setattr(self, "_path_step_run_worker_lock", lock)
    with lock:
        existing = getattr(self, "_path_step_run_worker_thread", None)
        if existing is not None and existing.is_alive():
            return
        worker = Thread(target=_path_step_run_worker_loop, args=(self,), daemon=True)
        setattr(self, "_path_step_run_worker_thread", worker)
        worker.start()


def _path_step_run_worker_loop(self: Any) -> None:
    idle_ticks = 0
    while idle_ticks < PATH_STEP_RUNNER_IDLE_TICKS:
        if _path_step_run_worker_tick(self):
            idle_ticks = 0
            continue
        idle_ticks += 1
        if idle_ticks < PATH_STEP_RUNNER_IDLE_TICKS:
            time.sleep(PATH_STEP_RUNNER_IDLE_SLEEP_SECONDS)


def _path_step_run_worker_tick(self: Any) -> bool:
    did_work = False
    for failed in self.repository.sweep_path_step_runs():
        did_work = True
        self.repository.maybe_retry_path_step_run(failed.run_id, reason="sweeper_retry")
    claimed = self.repository.claim_path_step_run(
        runtime_id=PATH_STEP_RUNNER_RUNTIME_ID,
        lease_seconds=PATH_STEP_RUNNER_LEASE_SECONDS,
    )
    if claimed is None:
        return did_work
    _execute_claimed_path_step_run(self, claimed)
    return True


def _execute_path_step_run(self: Any, run_id: str) -> None:
    """Compatibility helper for tests and manual maintenance."""
    loaded = self.repository.load_path_step_run(run_id)
    if loaded is None:
        return
    if loaded.status == "queued":
        claimed = self.repository.claim_path_step_run(
            runtime_id=PATH_STEP_RUNNER_RUNTIME_ID,
            lease_seconds=PATH_STEP_RUNNER_LEASE_SECONDS,
        )
        if claimed is None or claimed.run_id != run_id:
            return
        _execute_claimed_path_step_run(self, claimed)
        return
    _execute_claimed_path_step_run(self, loaded)


def _execute_claimed_path_step_run(self: Any, run: PathStepRunRecord) -> None:
    if run.status in {"completed", "failed", "cancelled"}:
        return
    latest_run = self.repository.load_path_step_run(run.run_id)
    if latest_run is None or latest_run.status in {"completed", "failed", "cancelled"}:
        return
    expected_runtime_id = run.runtime_id or PATH_STEP_RUNNER_RUNTIME_ID
    if latest_run.status not in {"dispatched", "running"}:
        return
    if latest_run.runtime_id != expected_runtime_id or (run.claim_token and latest_run.claim_token != run.claim_token):
        return
    if run.status == "dispatched" and latest_run.status == "running":
        return
    run = latest_run
    step = self.repository.load_path_step(run.path_step_id)
    if step is None:
        self.repository.update_path_step_run(
            run.run_id,
            status="failed",
            progress_stage="missing_step",
            progress_detail="Path step no longer exists.",
            failure_reason="missing_step",
            runtime_id=PATH_STEP_RUNNER_RUNTIME_ID,
        )
        return
    path = self.repository.load_path(step.path_id)
    heartbeat_stop = Event()
    heartbeat_thread: Thread | None = None
    try:
        if run.status == "dispatched":
            running = self.repository.start_path_step_run(
                run.run_id,
                runtime_id=run.runtime_id or PATH_STEP_RUNNER_RUNTIME_ID,
                claim_token=run.claim_token,
                lease_seconds=PATH_STEP_RUNNER_LEASE_SECONDS,
            )
        else:
            running = self.repository.update_path_step_run(
                run.run_id,
                status="running",
                progress_stage="running",
                progress_detail="Baby runtime started execution.",
                runtime_id=PATH_STEP_RUNNER_RUNTIME_ID,
            )
        running = self.repository.heartbeat_path_step_run(
            running.run_id,
            runtime_id=running.runtime_id or PATH_STEP_RUNNER_RUNTIME_ID,
            claim_token=running.claim_token,
            lease_seconds=PATH_STEP_RUNNER_LEASE_SECONDS,
            progress_stage="prepare_prompt",
            progress_detail="Preparing the delegated Path step prompt.",
            progress_current=1,
            progress_total=4,
        )
        episode_id = _ensure_path_run_episode(self, running, step, path)
        if running.session_id != episode_id:
            running = self.repository.update_path_step_run(
                running.run_id,
                session_id=episode_id,
            )
        _sync_path_step_comments_to_episode_history(self, step, episode_id)
        heartbeat_thread = Thread(
            target=_path_step_run_heartbeat_loop,
            args=(self, running.run_id, running.runtime_id or PATH_STEP_RUNNER_RUNTIME_ID, running.claim_token, heartbeat_stop),
            daemon=True,
        )
        heartbeat_thread.start()
        self.repository.heartbeat_path_step_run(
            running.run_id,
            runtime_id=running.runtime_id or PATH_STEP_RUNNER_RUNTIME_ID,
            claim_token=running.claim_token,
            lease_seconds=PATH_STEP_RUNNER_LEASE_SECONDS,
            progress_stage="model_run",
            progress_detail="Running with the configured model.",
            progress_current=2,
            progress_total=4,
        )
        local_cli_result_text = _run_path_step_local_cli_baby(
            self,
            running,
            step,
            path,
            prompt=_path_run_local_cli_task_prompt(self.repository, running, step, path),
        )
        if local_cli_result_text is not None:
            result_text = local_cli_result_text
        else:
            result = self.run_loop(
                episode_id,
                prompt=_path_run_prompt(self.repository, running, step, path),
                state_query="path step run",
                source_event_type="turn.internal",
            )
            if _path_run_result_failed(result):
                raise RuntimeError(_path_run_result_text(result) or "Path run failed.")
            result_text = _path_run_result_text(result)
        self.repository.heartbeat_path_step_run(
            running.run_id,
            runtime_id=running.runtime_id or PATH_STEP_RUNNER_RUNTIME_ID,
            claim_token=running.claim_token,
            lease_seconds=PATH_STEP_RUNNER_LEASE_SECONDS,
            progress_stage="learning_summary",
            progress_detail="Capturing the learning summary.",
            progress_current=3,
            progress_total=4,
        )
        refreshed_run = self.repository.load_path_step_run(run.run_id) or running
        if refreshed_run.status not in {"failed", "cancelled"} and not _has_learning_summary_for_run(
            self.repository,
            run.run_id,
            path_step_id=step.path_step_id,
        ):
            summary = self.repository.write_learning_summary(
                path_step_id=step.path_step_id,
                run_id=run.run_id,
                what_done=result_text or f"Ran Path step: {step.title}",
                why_it_matters="This closes the execution loop with a durable learning summary.",
                how_it_was_done="The configured model executed the Path step run and produced a concise outcome.",
                knowledge=_path_run_knowledge(step, path),
                human_takeaway=result_text or f"Core takeaway from {step.title}.",
                created_by_elephant_id=running.assignee_elephant_id,
                metadata={"source": PATH_STEP_RUNNER_RUNTIME_ID, "episode_id": episode_id},
            )
            _index_learning_summary(self, summary)
        _ensure_path_run_output_comment(
            self,
            running,
            step,
            result_text,
            episode_id=episode_id,
        )
        _sync_path_step_comments_to_episode_history(self, step, episode_id)
        final_run = self.repository.load_path_step_run(run.run_id)
        if final_run is not None and final_run.status not in {"failed", "cancelled"}:
            self.repository.update_path_step_run(
                run.run_id,
                status="completed",
                progress_stage="completed",
                progress_detail="Path step run completed.",
                progress_current=4,
                progress_total=4,
            )
    except Exception as error:
        failure_reason = _classify_path_step_run_failure(error)
        if failure_reason == "runtime_claim_changed":
            return
        try:
            self.repository.update_path_step_run(
                run.run_id,
                status="failed",
                progress_stage="failed",
                progress_detail=str(error),
                failure_reason=failure_reason,
                runtime_id=PATH_STEP_RUNNER_RUNTIME_ID,
            )
            self.repository.maybe_retry_path_step_run(run.run_id, reason=failure_reason)
        except Exception:
            return
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)


def _path_step_run_heartbeat_loop(
    self: Any,
    run_id: str,
    runtime_id: str,
    claim_token: str,
    stop: Event,
) -> None:
    while not stop.wait(PATH_STEP_RUNNER_HEARTBEAT_SECONDS):
        try:
            self.repository.heartbeat_path_step_run(
                run_id,
                runtime_id=runtime_id,
                claim_token=claim_token,
                lease_seconds=PATH_STEP_RUNNER_LEASE_SECONDS,
            )
        except Exception:
            return


def _run_path_step_local_cli_baby(
    self: Any,
    run: PathStepRunRecord,
    step: PathStepRecord,
    path: PathRecord | None,
    *,
    prompt: str,
) -> str | None:
    state = _load_path_run_elephant_state(self.repository, run, step, path)
    if state is None:
        return None
    metadata = dict(getattr(state, "metadata", {}) or {})
    backend = str(metadata.get("backend") or metadata.get("execution_backend") or "").strip().lower()
    if backend and backend not in {"local_cli", "cli", "local_agent"}:
        return None
    runtime_id = str(metadata.get("runtime_id") or "").strip()
    if not runtime_id:
        return None
    load_runtime = getattr(self.repository, "load_local_agent_runtime", None)
    runtime_record = load_runtime(runtime_id) if callable(load_runtime) else None
    if runtime_record is None:
        raise RuntimeError(f"local CLI runtime is missing: {runtime_id}")
    if not getattr(runtime_record, "can_execute", False):
        raise RuntimeError(f"local CLI runtime is not executable: {runtime_id}")
    self.repository.heartbeat_path_step_run(
        run.run_id,
        runtime_id=run.runtime_id or PATH_STEP_RUNNER_RUNTIME_ID,
        claim_token=run.claim_token,
        lease_seconds=PATH_STEP_RUNNER_LEASE_SECONDS,
        progress_stage="local_cli_run",
        progress_detail=f"Running local CLI engine {getattr(runtime_record, 'display_name', '') or runtime_record.provider_id}.",
        progress_current=2,
        progress_total=4,
    )
    cwd = _path_run_local_cli_cwd(self, state)
    self.repository.update_path_step_run(
        run.run_id,
        work_dir=str(cwd),
        metadata={
            "execution_backend": "local_cli",
            "engine_runtime_id": runtime_id,
            "engine_display_name": str(getattr(runtime_record, "display_name", "") or ""),
            "engine_provider_id": str(getattr(runtime_record, "provider_id", "") or ""),
        },
    )
    result = run_local_agent_cli(
        runtime_record,
        prompt=_path_run_local_cli_prompt(prompt=prompt, state=state, runtime_record=runtime_record),
        cwd=cwd,
        model=str(getattr(runtime_record, "default_model", "") or ""),
        timeout_seconds=_path_run_local_cli_timeout(metadata),
    )
    if result.status != "completed":
        raise RuntimeError(result.summary or f"local CLI runtime failed: {runtime_id}")
    return result.summary


def _load_path_run_elephant_state(
    repository: Any,
    run: PathStepRunRecord | None,
    step: PathStepRecord,
    path: PathRecord | None,
) -> Any | None:
    elephant_id = _path_run_elephant_id(run, step, path)
    if not elephant_id:
        return None
    return repository.load_state(f"state:{elephant_id}")


def _path_run_local_cli_prompt(*, prompt: str, state: Any, runtime_record: Any) -> str:
    metadata = dict(getattr(state, "metadata", {}) or {})
    role_title = str(metadata.get("role_title") or getattr(state, "elephant_name", "") or "baby elephant").strip()
    role_prompt = str(metadata.get("role_prompt") or metadata.get("instruction") or "").strip()
    identity = str(getattr(state, "elephant_identity_text", "") or "").strip()
    sections = [
        "[SYSTEM: You are running as a delegated baby elephant for an Elephant Path step.]",
        "Return a concise final result for Mother Elephant. Do not delegate further.",
        "You do not have Elephant runtime tools in this local CLI execution.",
        "Do not try to call tool.paths.manage or any Elephant API tool; return only the final plain-text result.",
        f"Baby elephant id: {getattr(state, 'elephant_id', '')}",
        f"Baby elephant name: {getattr(state, 'elephant_name', '')}",
        f"Role: {role_title}",
        f"Local CLI engine: {getattr(runtime_record, 'display_name', '')} ({getattr(runtime_record, 'provider_id', '')})",
    ]
    if role_prompt:
        sections.extend(["", "Role instructions:", role_prompt])
    if identity:
        sections.extend(["", "Baby elephant identity:", identity])
    sections.extend(["", "Delegated Path step:", prompt])
    return "\n".join(sections).strip()


def _path_run_local_cli_cwd(self: Any, state: Any) -> Path:
    install_root = getattr(getattr(self, "config", None), "install_root", None)
    root = Path(install_root) if install_root is not None else Path.home() / ".elephant"
    cwd = root / "workspaces" / str(getattr(state, "elephant_id", "") or "local-cli-baby")
    cwd.mkdir(parents=True, exist_ok=True)
    if not (cwd / ".git").exists():
        subprocess.run(
            ["git", "init", "-q"],
            cwd=str(cwd),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return cwd


def _path_run_local_cli_timeout(metadata: Mapping[str, Any]) -> int:
    raw = str(metadata.get("timeout_seconds") or metadata.get("timeoutSeconds") or "1800").strip()
    try:
        return max(1, min(int(raw), 86400))
    except ValueError:
        return 1800


def _classify_path_step_run_failure(error: Exception) -> str:
    text = str(error or "").strip().lower()
    if "not claim-owned" in text:
        return "runtime_claim_changed"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "cancel" in text:
        return "cancelled"
    if "rate limit" in text or "429" in text:
        return "rate_limited"
    if "api key" in text or "provider" in text or "configuration" in text or "auth" in text:
        return "provider_config"
    return "agent_error"


def _ensure_path_run_episode(self: Any, run: PathStepRunRecord, step: PathStepRecord, path: PathRecord | None) -> str:
    return _ensure_path_step_episode(self, step, path, run=run)


def _ensure_path_step_episode(
    self: Any,
    step: PathStepRecord,
    path: PathRecord | None,
    *,
    run: PathStepRunRecord | None = None,
) -> str:
    personal_model_id = (run.personal_model_id if run is not None else "") or step.personal_model_id or DEFAULT_PERSONAL_MODEL_ID
    model = self.repository.ensure_default_personal_model(personal_model_id=personal_model_id)
    elephant_id = _path_run_elephant_id(run, step, path)
    state_id = f"state:{elephant_id}"
    state = self.repository.load_state(state_id)
    if state is None:
        state = self.repository.create_state(
            personal_model_id=model.personal_model_id,
            state_id=state_id,
            state_anchor=f"elephant:{elephant_id}",
            elephant_id=elephant_id,
            elephant_name=_display_name(elephant_id),
            identity_mode="baby" if elephant_id != "mother-elephant" else "mother",
            initiative="delegated",
            working_style="path_runner",
            surface_bindings=("api", "paths"),
            summary=f"{_display_name(elephant_id)} can execute delegated Path steps.",
            metadata={"created_by": "api.path-runner"},
        )
    existing_episode = _load_path_step_episode(self.repository, step.related_episode_id)
    if existing_episode is not None and existing_episode.status != "closed":
        return existing_episode.episode_id
    episode = Episode(
        episode_id=f"path-step-{uuid4().hex}",
        state_id=state.state_id,
        personal_model_id=model.personal_model_id,
        entry_surface="api",
        elephant_id=state.elephant_id,
        status="open",
        started_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        metadata={
            "source": PATH_STEP_RUNNER_RUNTIME_ID,
            "path_id": step.path_id,
            "path_step_id": step.path_step_id,
            "path_title": path.title if path is not None else "",
            "path_step_title": step.title,
        },
    )
    self.repository.upsert_episode_state(episode)
    self.repository.upsert_path_step(
        replace(
            step,
            related_episode_id=episode.episode_id,
            metadata={**dict(step.metadata), "conversation_episode_id": episode.episode_id},
        )
    )
    return episode.episode_id


def _load_path_step_episode(repository: Any, episode_id: str | None) -> Episode | None:
    cleaned = str(episode_id or "").strip()
    if not cleaned:
        return None
    for method_name in ("load_episode_state", "load_episode"):
        loader = getattr(repository, method_name, None)
        if not callable(loader):
            continue
        try:
            loaded = loader(cleaned)
        except Exception:
            continue
        if loaded is not None:
            return loaded
    return None


def _path_run_prompt(
    repository: Any,
    run: PathStepRunRecord,
    step: PathStepRecord,
    path: PathRecord | None,
) -> str:
    path_title = path.title if path is not None else "Untitled Path"
    path_detail = path.description if path is not None else ""
    step_detail = step.description.strip() or step.title
    lines = [
        "Continue this delegated Elephant Agent Path step using the existing conversation history.",
        "",
        "Execution context:",
        f"Path: {path_title}",
        f"Path context: {path_detail}",
        f"Step: {step.title}",
        f"Step detail: {step_detail}",
        f"Run id: {run.run_id}",
        f"Path step id: {step.path_step_id}",
    ]
    latest_comment = run.metadata.get("trigger_comment_body", "").strip() or _path_latest_human_comment_text(
        repository,
        step.path_step_id,
    )
    if latest_comment:
        lines.extend(("", "Latest human message:", latest_comment))
    else:
        lines.extend(("", "No new human message was attached to this run; execute the step as currently written."))
    lines.extend(
        [
            "",
            "Do the smallest useful version of the work directly. When finished, call tool.paths.manage with:",
            "- action: write_summary",
            f"- path_step_id: {step.path_step_id}",
            f"- run_id: {run.run_id}",
            "- what_done, why_it_matters, how_it_was_done, knowledge, and human_takeaway",
            "",
            "The human takeaway should be the core essence the user should absorb from this step.",
            "If you have a user-facing result, call tool.paths.manage action=write_comment with the same run_id.",
            "If the work is blocked, call tool.paths.manage action=update_run with status=failed and a failure_reason.",
        ]
    )
    return "\n".join(lines)


def _path_run_local_cli_task_prompt(
    repository: Any,
    run: PathStepRunRecord,
    step: PathStepRecord,
    path: PathRecord | None,
) -> str:
    path_title = path.title if path is not None else "Untitled Path"
    path_detail = path.description if path is not None else ""
    step_detail = step.description.strip() or step.title
    lines = [
        "Execute this delegated Elephant Agent Path step and return only the final plain-text result.",
        "",
        "Execution context:",
        f"Path: {path_title}",
        f"Path context: {path_detail}",
        f"Step: {step.title}",
        f"Step detail: {step_detail}",
        f"Run id: {run.run_id}",
        f"Path step id: {step.path_step_id}",
    ]
    latest_comment = run.metadata.get("trigger_comment_body", "").strip() or _path_latest_human_comment_text(
        repository,
        step.path_step_id,
    )
    if latest_comment:
        lines.extend(("", "Latest human message:", latest_comment))
    else:
        lines.extend(("", "No new human message was attached to this run; execute the step as currently written."))
    lines.extend(
        [
            "",
            "Do the smallest useful version of the work directly.",
            "Do not call Elephant tools or APIs. The parent runtime will write the Path comment and learning summary.",
            "Keep the final result concise and include any exact marker the step asks for.",
        ]
    )
    return "\n".join(lines)


def _path_latest_human_comment_text(repository: Any, path_step_id: str) -> str:
    list_comments = getattr(repository, "list_path_step_comments", None)
    if not callable(list_comments):
        return ""
    try:
        comments = list_comments(path_step_id=path_step_id, limit=50)
    except Exception:
        return ""
    for comment in reversed(comments):
        if str(getattr(comment, "author_kind", "") or "").strip().lower() != "user":
            continue
        body = str(getattr(comment, "body", "") or "").strip()
        if not body:
            continue
        return body
    return ""


def _sync_path_step_comments_to_episode_history(self: Any, step: PathStepRecord, episode_id: str) -> None:
    list_comments = getattr(self.repository, "list_path_step_comments", None)
    if not callable(list_comments):
        return
    try:
        comments = list_comments(path_step_id=step.path_step_id, limit=200)
    except Exception:
        return
    _replace_path_step_history_messages(self, episode_id, step.path_step_id, comments)


def _append_path_step_comment_to_episode_history(
    self: Any,
    episode_id: str,
    comment: PathStepCommentRecord,
) -> None:
    _replace_path_step_history_messages(self, episode_id, comment.path_step_id, (comment,))


def _replace_path_step_history_messages(
    self: Any,
    episode_id: str,
    path_step_id: str,
    comments: tuple[PathStepCommentRecord, ...],
) -> None:
    cleaned_episode_id = str(episode_id or "").strip()
    if not cleaned_episode_id:
        return
    try:
        store = FileEpochStore(self.repository.database_path.parent)
    except Exception:
        return
    epoch = store.load(cleaned_episode_id) or SessionContextEpoch(session_id=cleaned_episode_id)
    scoped_messages_by_id = {
        str(message.metadata.get("path_step_comment_id") or ""): message
        for message in epoch.history_messages
        if str(message.metadata.get("projection_surface") or "") == "path_step"
        and str(message.metadata.get("path_step_id") or "") == path_step_id
        and str(message.metadata.get("path_step_comment_id") or "")
    }
    for comment in comments:
        message = _prompt_message_for_path_step_comment(comment)
        if message is not None:
            scoped_messages_by_id[comment.comment_id] = message
    if not scoped_messages_by_id:
        return
    retained_messages = tuple(
        message
        for message in epoch.history_messages
        if not (
            str(message.metadata.get("projection_surface") or "") == "path_step"
            and str(message.metadata.get("path_step_id") or "") == path_step_id
        )
    )
    scoped_messages = tuple(sorted(scoped_messages_by_id.values(), key=_path_step_history_message_sort_key))
    store.save(replace(epoch, history_messages=(*retained_messages, *scoped_messages)))


def _path_step_history_message_sort_key(message: PromptMessage) -> tuple[str, str]:
    metadata = dict(getattr(message, "metadata", {}) or {})
    return (
        str(metadata.get("created_at") or ""),
        str(metadata.get("path_step_comment_id") or ""),
    )


def _prompt_message_for_path_step_comment(comment: PathStepCommentRecord) -> PromptMessage | None:
    body = str(comment.body or "").strip()
    if not body:
        return None
    author_kind = str(comment.author_kind or "").strip().lower()
    if author_kind == "user":
        role = "user"
    elif author_kind == "system":
        role = "system"
    else:
        role = "assistant"
    metadata = {
        "projection_surface": "path_step",
        "path_step_comment_id": comment.comment_id,
        "path_step_id": comment.path_step_id,
        "path_id": comment.path_id,
        "comment_type": comment.comment_type,
        "author_kind": comment.author_kind,
        "author_id": comment.author_id,
        "run_id": comment.run_id,
    }
    if comment.created_at is not None:
        metadata["created_at"] = comment.created_at.isoformat()
    return PromptMessage(role=role, content=body, metadata=metadata)


def _ensure_path_run_output_comment(
    self: Any,
    run: PathStepRunRecord,
    step: PathStepRecord,
    body: str,
    *,
    episode_id: str,
) -> None:
    text = str(body or "").strip()
    if not text:
        return
    list_comments = getattr(self.repository, "list_path_step_comments", None)
    create_comment = getattr(self.repository, "create_path_step_comment", None)
    if not callable(list_comments) or not callable(create_comment):
        return
    try:
        existing = list_comments(path_step_id=step.path_step_id, run_id=run.run_id, author_kind="elephant", limit=1)
        if existing:
            return
        create_comment(
            path_step_id=step.path_step_id,
            body=text,
            author_kind="elephant",
            author_id=run.assignee_elephant_id or step.assignee_elephant_id or "mother-elephant",
            comment_type="run_output",
            run_id=run.run_id,
            metadata={"source": PATH_STEP_RUNNER_RUNTIME_ID, "episode_id": episode_id},
        )
    except Exception:
        return


def _path_run_elephant_id(run: PathStepRunRecord | None, step: PathStepRecord, path: PathRecord | None) -> str:
    for value in (
        run.assignee_elephant_id if run is not None else "",
        step.assignee_elephant_id,
        path.owner_elephant_id if path is not None else "",
    ):
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return "mother-elephant"


def _display_name(elephant_id: str) -> str:
    cleaned = elephant_id.replace(":", " ").replace("-", " ").replace("_", " ").strip()
    return cleaned.title() if cleaned else "Mother Elephant"


def _has_learning_summary_for_run(repository: Any, run_id: str, *, path_step_id: str) -> bool:
    list_summaries = getattr(repository, "list_learning_summaries", None)
    if not callable(list_summaries):
        return False
    try:
        return any(summary.run_id == run_id for summary in list_summaries(path_step_id=path_step_id, limit=10))
    except Exception:
        return False


def _path_run_result_failed(result: Any) -> bool:
    outcome = getattr(result, "outcome", result)
    execution = getattr(outcome, "execution", outcome)
    return str(getattr(execution, "outcome", "") or "").strip().lower() in {"failed", "error"}


def _path_run_result_text(result: Any) -> str:
    outcome = getattr(result, "outcome", result)
    execution = getattr(outcome, "execution", outcome)
    return str(getattr(execution, "summary", "") or getattr(outcome, "summary", "") or "").strip()


def _path_run_knowledge(step: PathStepRecord, path: PathRecord | None) -> str:
    parts = [
        f"Path step: {step.title}",
        step.description,
        f"Path: {path.title}" if path is not None else "",
    ]
    return " | ".join(part for part in parts if str(part or "").strip())
