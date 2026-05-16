"""Tool, cron, skill, and extension management methods for the CLI runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any

from packages.embeddings import embedding_runtime_is_loaded, embedding_runtime_state
from packages.contracts.layers import Episode
from packages.contracts.runtime import ExperienceRecord, ExecutionResult
from packages.cron import CronJob, CronJobExecution
from packages.runtime_config import global_config_path_for_state_dir, load_global_config, save_extensions_to_config, load_extensions_from_config
from packages.growth import GrowthUpdate, ProgressionProjection, ProgressionTransition
from packages.skills import PublicSkillSourceDescriptor, SkillDefinition, SkillHubEntry, SkillManifestLoadRecord, SkillPackageLoader, SkillSearchEntry, build_installed_skill_provenance, build_public_skill_source_descriptor, install_bucket_for_source_descriptor, load_skill_package_definition, materialize_skill_package, public_skill_source_descriptor_from_metadata
from packages.skills.authoring import write_skill_package
from packages.state import (
    PromptContract,
    PromptMode,
    build_prompt_contract,
    elephant_id_from_session,
    personality_presets,
    profile_with_authored_elephant_identity,
)
from packages.tools import BuiltinToolDependencies, ToolAudience, ToolDefinition, ToolManifestLoadRecord, sync_custom_mcp_tools
from packages.tools.adapters import StructuredClarifySurface
from packages.understanding import PersonalModelUnderstandingSurface

from .runtime_extensions import CliExtensionManifest, build_skill_runtime, build_tool_runtime, load_extension_manifest, sanitize_extension_manifest_payload, serialize_manifest_path
from .runtime_extensions_skill_sources import install_record_detail as _install_record_detail, installed_skill_record as _installed_skill_record, matching_install_record as _matching_install_record, normalized_install_requester as _normalized_install_requester, record_install_reference as _record_install_reference, remote_skill_definition as _remote_skill_definition, source_descriptor_for_hub_entry as _source_descriptor_for_hub_entry, source_descriptor_for_path as _source_descriptor_for_path
from .runtime_cron_sub_agents import compose_cron_prompt
from .runtime_growth_surface import inspect_experiences as _inspect_experiences, inspect_growth as _inspect_growth, inspect_growth_transition as _inspect_growth_transition
from .runtime_sub_agents import CliRuntimeSubAgentsMixin
from .runtime_support import _path_is_within, _utc_now


def _as_result_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]
    return [value]


def _normalize_result_section(
    value: Mapping[str, Any] | None,
    *,
    defaults: Mapping[str, object],
    aliases: Mapping[str, tuple[str, ...]],
) -> dict[str, object]:
    raw = dict(value or {})
    normalized = {key: (list(default) if isinstance(default, list) else default) for key, default in defaults.items()}
    for canonical, alias_names in aliases.items():
        merged: list[object] = []
        merged.extend(_as_result_list(raw.get(canonical)))
        for alias in alias_names:
            merged.extend(_as_result_list(raw.pop(alias, None)))
        if merged:
            normalized[canonical] = merged
    for key, item in raw.items():
        if key not in normalized:
            normalized[key] = item
    if not str(normalized.get("notes") or "").strip():
        normalized["notes"] = str(raw.get("note") or "")
    return normalized


class CliRuntimeExtensionsMixin(CliRuntimeSubAgentsMixin):
    def _save_extensions_manifest(self, extensions: Mapping[str, Any]) -> None:
        """Write extension manifest data to config.yaml."""
        config_path = global_config_path_for_state_dir(self.paths.state_dir)
        save_extensions_to_config(
            config_path,
            state_dir=self.paths.state_dir,
            extensions=extensions,
        )

    def personality_presets(self):
        return personality_presets()

    def prompt_contract(
        self,
        *,
        profile_id: str | None = None,
        prompt_mode: PromptMode = "full",
    ) -> PromptContract:
        loaded = self._load_profile(profile_id or self.current_profile().state.profile_id)
        session = self.latest_session()
        elephant_id = elephant_id_from_session(session) if session is not None else ""
        if session is not None and elephant_id and session.personal_model_id == loaded.state.profile_id:
            loaded = profile_with_authored_elephant_identity(
                loaded,
                self.paths.elephant_file_path(elephant_id),
            )
        return build_prompt_contract(loaded, prompt_mode=prompt_mode)

    def prepare_session_surface(self, session_id: str, *, steady_embeddings: bool = True) -> Episode:
        session = self._load_session(session_id)
        self._refresh_extensions(profile_id=session.personal_model_id)
        if steady_embeddings:
            self._steady_embedding_runtime()
        return session

    def _steady_embedding_runtime(self) -> None:
        evidence_retriever = getattr(self.recall_runtime.retriever, "evidence_retriever", None)
        embedding_service = getattr(evidence_retriever, "embedding_service", None)
        steady_async = getattr(embedding_service, "steady_async", None)
        if not callable(steady_async):
            return
        try:
            steady_async()
        except Exception:
            # Surface preparation should stay cheap and non-blocking even when the
            # local embedding runtime is missing or mid-bootstrap.
            return

    def state_focus_runtime_status(self) -> Mapping[str, object]:
        evidence_retriever = getattr(self.recall_runtime.retriever, "evidence_retriever", None)
        embedding_service = getattr(evidence_retriever, "embedding_service", None)
        if embedding_service is None:
            return {
                "health_status": "missing",
                "runtime_state": "cold",
                "embedding_ready": False,
                "summary": "no embedding runtime is attached to the active CLI memory retriever",
            }
        try:
            health = embedding_service.health()
        except Exception as error:
            return {
                "health_status": "failed",
                "runtime_state": "cold",
                "embedding_ready": False,
                "summary": str(error).strip() or error.__class__.__name__,
            }
        runtime_state = embedding_runtime_state(health)
        return {
            "health_status": health.status,
            "runtime_state": runtime_state,
            "embedding_ready": embedding_runtime_is_loaded(health),
            "summary": health.summary,
        }

    def _learning_state_for_session(self, session_id: str):
        session = self.inspect_session(session_id)
        elephant_id = self.elephant_id_for_session(session)
        if elephant_id:
            state = self.state_for_elephant(elephant_id)
            if state is not None:
                return state
        state = self.current_elephant_state()
        if state is None:
            raise KeyError(f"no active state for session: {session_id}")
        return state

    def _ensure_learning_worker_if_needed(self) -> bool:
        queued = self.repository.list_learning_jobs(statuses=("queued",), limit=1)
        if not queued:
            return False
        from apps.learning_worker_runtime import ensure_learning_worker_running

        return ensure_learning_worker_running(
            state_dir=self.paths.state_dir,
        )

    def schedule_learning_for_session(
        self,
        *,
        session_id: str,
        trigger: str,
        summary: str = "",
        metadata: Mapping[str, str] | None = None,
        job_type: str = "episode_boundary_learning",
        force_new: bool = False,
        start_worker: bool = True,
    ):
        session = self.inspect_session(session_id)
        state = self._learning_state_for_session(session_id)
        loops = self.repository.list_loops(episode_id=session_id)
        loop = loops[-1] if loops else None
        job = self.repository.enqueue_learning_job(
            job_type=job_type,
            trigger=trigger,
            personal_model_id=session.personal_model_id,
            state_id=state.state_id,
            episode_id=session_id,
            loop_id=loop.loop_id if loop is not None else None,
            summary=summary,
            metadata=metadata,
            force_new=force_new,
        )
        if start_worker:
            self._ensure_learning_worker_if_needed()
        return job

    def write_learning_result(
        self,
        *,
        session_id: str,
        job_id: str,
        status: str,
        summary: str,
        mode: str = "",
        pm_facts: Mapping[str, Any] | None = None,
        skill_affinities: Mapping[str, Any] | None = None,
        questions: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        followups: tuple[str, ...] = (),
        diagnostics: Mapping[str, Any] | None = None,
        personal_model_id: str = "",
        state_id: str = "",
    ) -> Mapping[str, Any]:
        session = self.inspect_session(session_id)
        resolved_pm_id = personal_model_id or session.personal_model_id
        state = self._learning_state_for_session(session_id)
        resolved_state_id = state_id or state.state_id
        job = self.repository.load_learning_job(job_id)
        if job is None:
            raise KeyError(f"learning job not found: {job_id}")
        if job.personal_model_id != resolved_pm_id:
            raise PermissionError(f"learning job does not belong to this personal model: {job_id}")
        normalized_status = status if status in {"completed", "partial", "no_op", "failed"} else "partial"
        normalized_mode = mode if mode in {"init_bootstrap", "episode_close", "im_idle", "context_compression", "manual"} else "manual"
        payload = {
            "job_id": job_id,
            "mode": normalized_mode,
            "status": normalized_status,
            "summary": summary,
            "pm_facts": _normalize_result_section(
                pm_facts,
                defaults={"created_refs": [], "updated_refs": [], "retired_refs": [], "notes": ""},
                aliases={
                    "created_refs": ("created", "created_ids", "created_facts"),
                    "updated_refs": ("updated", "updated_ids", "updated_facts"),
                    "retired_refs": ("retired", "retired_ids", "forgotten", "forgotten_refs"),
                },
            ),
            "skill_affinities": _normalize_result_section(
                skill_affinities,
                defaults={"included_refs": [], "excluded_refs": [], "candidate_refs": [], "notes": ""},
                aliases={
                    "included_refs": ("included", "included_ids", "created", "created_refs"),
                    "excluded_refs": ("excluded", "excluded_ids", "retired", "retired_refs"),
                    "candidate_refs": ("candidates", "candidate_ids"),
                },
            ),
            "questions": _normalize_result_section(
                questions,
                defaults={
                    "settled_ids": [],
                    "created_ids": [],
                    "updated_ids": [],
                    "next_ask_candidate_ids": [],
                    "dismissed_ids": [],
                    "notes": "",
                },
                aliases={
                    "settled_ids": ("settled", "answered", "answered_ids"),
                    "created_ids": ("created", "created_questions"),
                    "updated_ids": ("updated", "updated_questions"),
                    "next_ask_candidate_ids": ("next_candidates", "next_ask_candidates", "candidates"),
                    "dismissed_ids": ("dismissed", "dismissed_questions", "stale_ids"),
                },
            ),
            "context": {
                "episode_summary_updated": False,
                "continuation_note": "",
                "should_refresh_frozen_prefix": False,
                "should_refresh_skill_index": False,
                **dict(context or {}),
            },
            "followups": list(followups),
            "diagnostics": dict(diagnostics or {}),
        }
        self.repository.write_learning_job_result(
            job_id,
            payload,
            worker_id=getattr(job, "worker_id", None) or "learning-result-tool",
            progress_detail=summary,
        )
        return {"job_id": job_id, "status": normalized_status, "summary": summary, "learning_result": payload}

    # --- DiarySurface implementation ---

    def write_diary_entry(
        self,
        *,
        personal_model_id: str,
        entry_date: str,
        content: str,
        source_episode_ids: tuple[str, ...] = (),
        metadata: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        from uuid import uuid4
        from packages.contracts import DiaryEntry
        entry_id = f"diary:{uuid4().hex[:12]}"
        entry = DiaryEntry(
            entry_id=entry_id,
            personal_model_id=personal_model_id,
            entry_date=entry_date,
            content=content,
            generated_at=datetime.now(timezone.utc),
            source_episode_ids=source_episode_ids,
            metadata=dict(metadata) if metadata else {},
        )
        self.repository.upsert_diary_entry(entry)
        return {"entry_id": entry_id, "entry_date": entry_date, "status": "written"}

    def list_diary_entries(
        self,
        *,
        personal_model_id: str,
        limit: int = 30,
        before_date: str | None = None,
    ) -> Mapping[str, Any]:
        entries = self.repository.list_diary_entries(
            personal_model_id=personal_model_id,
            limit=limit,
            before_date=before_date,
        )
        return {
            "entries": [
                {"entry_id": e.entry_id, "entry_date": e.entry_date, "content": e.content}
                for e in entries
            ],
            "count": len(entries),
        }

    def learning_runtime_status(
        self,
        *,
        session_id: str,
        limit: int = 4,
    ) -> Mapping[str, object]:
        state = self._learning_state_for_session(session_id)
        jobs = self.repository.list_learning_jobs(
            statuses=("running", "queued", "failed", "completed"),
            state_id=state.state_id,
            limit=max(1, limit),
        )
        running = tuple(job for job in jobs if job.status == "running")
        queued = tuple(job for job in jobs if job.status == "queued")
        failed = tuple(job for job in jobs if job.status == "failed")
        completed = tuple(job for job in jobs if job.status == "completed")
        from apps.learning_worker_runtime import load_learning_worker_record, learning_worker_is_running

        worker_record = load_learning_worker_record(self.paths.state_dir) or {}
        return {
            "active": bool(running or queued),
            "worker_running": learning_worker_is_running(self.paths.state_dir),
            "worker_status": str(worker_record.get("status") or "stopped"),
            "worker_pid": worker_record.get("pid"),
            "active_job_id": worker_record.get("active_job_id"),
            "current_stage": str(worker_record.get("current_stage") or ""),
            "running_count": len(running),
            "queued_count": len(queued),
            "failed_count": len(failed),
            "completed_count": len(completed),
            "jobs": tuple(
                {
                    "job_id": job.job_id,
                    "job_type": job.job_type,
                    "trigger": job.trigger,
                    "status": job.status,
                    "summary": job.summary,
                    "progress_stage": job.progress_stage,
                    "progress_detail": job.progress_detail,
                    "attempt_count": job.attempt_count,
                    "max_attempts": job.max_attempts,
                    "result_job_id": job.job_id if job.result_json else "",
                    "result_status": str(dict(job.result_json).get("status") or ""),
                    "result_summary": str(dict(job.result_json).get("summary") or ""),
                    "learning_result": dict(job.result_json),
                }
                for job in jobs
            ),
        }

    def tool_catalog(self, *, session_id: str | None = None, audience: ToolAudience | None = None) -> tuple[ToolDefinition, ...]:
        if session_id is not None:
            self.prepare_session_surface(session_id, steady_embeddings=False)
        return self.tool_runtime.list_tools(audience=audience)

    def inspect_tool(self, tool_id: str, *, session_id: str | None = None) -> ToolDefinition:
        if session_id is not None:
            self.prepare_session_surface(session_id, steady_embeddings=False)
        tool = self.tool_runtime.describe(tool_id)
        if tool is None:
            raise KeyError(tool_id)
        return tool

    def set_tool_enabled(
        self,
        tool_id: str,
        enabled: bool,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> ToolDefinition:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        self._refresh_extensions(profile_id=resolved_profile_id)
        updated = self.tool_runtime.set_enabled(tool_id, enabled)
        self._write_extension_override(
            "tool_overrides",
            tool_id,
            enabled,
            profile_id=resolved_profile_id,
        )
        return updated

    def install_tool_manifest(
        self,
        manifest_path: str | Path,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> ToolManifestLoadRecord:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        target_profile = self._load_profile(resolved_profile_id)
        resolved_path = Path(manifest_path).expanduser().resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(resolved_path)
        profile_dir = Path(target_profile.profile_dir)
        manifest = dict(target_profile.manifest)
        existing_paths = list(load_extension_manifest(manifest, profile_dir=profile_dir).tool_manifest_paths)
        if resolved_path not in existing_paths:
            existing_paths.append(resolved_path)
        manifest["tool_manifests"] = [
            serialize_manifest_path(path, profile_dir=profile_dir)
            for path in existing_paths
        ]
        self._save_extensions_manifest(manifest)
        self._refresh_extensions(profile_id=resolved_profile_id)
        return self._tool_manifest_load_record(resolved_path)

    def run_tool(
        self,
        tool_id: str,
        arguments: Mapping[str, Any],
        *,
        session_id: str,
    ) -> ExecutionResult:
        self.prepare_session_surface(session_id)
        return self.tool_runtime.invoke(tool_id, arguments, session_id=session_id, requester="operator")

    def set_clarify_surface(self, surface: Any) -> None:
        object.__setattr__(self, "clarify_surface", surface)
        self._refresh_extensions(profile_id=self.current_profile().state.profile_id)

    def cron_jobs(self, *, session_id: str) -> tuple[CronJob, ...]:
        profile_id, elephant_id = self._cron_scope(session_id)
        return self.cron_runtime.list_jobs(
            profile_id=profile_id,
            elephant_id=elephant_id,
        )

    def inspect_cron_job(self, job_id: str) -> CronJob:
        return self.cron_runtime.inspect_job(job_id)

    def create_cron_job(
        self,
        *,
        session_id: str,
        name: str,
        schedule: str,
        payload: Mapping[str, Any],
        skills: tuple[str, ...] = (),
    ) -> CronJob:
        self._authorize_write(
            operation="cli.cron.create",
            session_id=session_id,
            description=f"{name} @ {schedule}",
            metadata={"action_kind": "prompt"},
        )
        profile_id, elephant_id = self._cron_scope(session_id)
        stored_payload = dict(payload)
        if skills:
            stored_payload["skills"] = list(dict.fromkeys(skill.strip() for skill in skills if skill.strip()))
        return self.cron_runtime.create_job(
            name=name,
            schedule_text=schedule,
            payload=stored_payload,
            profile_id=profile_id,
            elephant_id=elephant_id,
        )

    def pause_cron_job(self, job_id: str) -> CronJob:
        job = self.cron_runtime.inspect_job(job_id)
        scoped_session = self.latest_session_for_elephant(job.elephant_id or "") if job.elephant_id else None
        self._authorize_write(
            operation="cli.cron.pause",
            session_id=scoped_session.episode_id if scoped_session is not None else None,
            description=job.name,
            metadata={"job_id": job_id},
        )
        return self.cron_runtime.pause_job(job_id)

    def resume_cron_job(self, job_id: str) -> CronJob:
        job = self.cron_runtime.inspect_job(job_id)
        scoped_session = self.latest_session_for_elephant(job.elephant_id or "") if job.elephant_id else None
        self._authorize_write(
            operation="cli.cron.resume",
            session_id=scoped_session.episode_id if scoped_session is not None else None,
            description=job.name,
            metadata={"job_id": job_id},
        )
        return self.cron_runtime.resume_job(job_id)

    def remove_cron_job(self, job_id: str) -> CronJob:
        job = self.cron_runtime.inspect_job(job_id)
        scoped_session = self.latest_session_for_elephant(job.elephant_id or "") if job.elephant_id else None
        self._authorize_write(
            operation="cli.cron.remove",
            session_id=scoped_session.episode_id if scoped_session is not None else None,
            description=job.name,
            is_destructive=True,
            metadata={"job_id": job_id},
        )
        return self.cron_runtime.remove_job(job_id)

    def run_due_cron_jobs(self, *, session_id: str) -> tuple[CronJobExecution, ...]:
        session = self._load_session(session_id)
        loaded = self._load_profile(session.personal_model_id)

        def executor(job: CronJob) -> tuple[str, str]:
            return self._execute_cron_job(job, session_id=session_id)

        return self.cron_runtime.run_due(
            executor,
            profile_id=loaded.state.profile_id,
            elephant_id=self.elephant_id_for_session(session),
        )

    def run_due_cron_jobs_for_scheduler(self) -> tuple[CronJobExecution, ...]:
        def executor(job: CronJob) -> tuple[str, str]:
            session = self._cron_session_for_job(job)
            if session is None:
                return ("failed", f"{job.name} skipped because no matching session is available.")
            return self._execute_cron_job(job, session_id=session.episode_id)

        return self.cron_runtime.run_due(executor)

    def run_cron_job_now(self, job_id: str) -> CronJobExecution:
        """Execute one cron job immediately, regardless of its ``next_run_at``.

        Used by the dashboard's "Verify" button (API ``POST /v1/operator/cron/<id>/run``)
        to let the operator fire a job on demand instead of waiting for the next
        scheduler tick. Goes through the exact same pipeline the scheduler uses
        (``_execute_cron_job`` → ``CronRuntime.begin_execution`` →
        ``record_execution_result``), so the job's ``run_count``/``last_run_at``
        advance, the schedule is rolled forward, and delivery (if wired) fires
        identically. A synthetic ``CronJobExecution`` is returned so callers can
        route it to the shared delivery callback.
        """
        job = self.cron_runtime.inspect_job(job_id)
        now = datetime.now().astimezone()
        started = self.cron_runtime.begin_execution(job_id, now=now)
        session = self._cron_session_for_job(started.job)
        if session is None:
            outcome, summary = ("failed", f"{started.job.name} skipped because no matching session is available.")
        else:
            outcome, summary = self._execute_cron_job(started.job, session_id=session.episode_id)
        return self.cron_runtime.record_execution_result(
            job_id,
            outcome=outcome,
            summary=summary,
            now=now,
        )

    def _execute_cron_job(
        self,
        job: CronJob,
        *,
        session_id: str,
    ) -> tuple[str, str]:
        try:
            if job.action_kind == "learning":
                return self._execute_cron_learning_job(job, session_id=session_id)
            if job.action_kind != "prompt":
                raise ValueError(f"unsupported cron action kind: {job.action_kind}")
            prompt = str(job.payload.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("scheduled prompt jobs require a non-empty prompt")
            result = self.explain_next_step(
                session_id=session_id,
                prompt=compose_cron_prompt(self, job, user_prompt=prompt, session_id=session_id),
                event_payload={
                    "message": f"cron job: {job.name}",
                    "summary": f"scheduled prompt job: {job.name}",
                    "content": prompt,
                },
            )
            return ("success", result.execution.summary)
        except Exception as error:
            return ("failed", f"{job.name} failed: {error}")

    def _execute_cron_learning_job(
        self,
        job: CronJob,
        *,
        session_id: str,
    ) -> tuple[str, str]:
        """Execute a cron job that triggers a learning agent."""
        from datetime import date as date_type, timedelta
        trigger = str(job.payload.get("trigger") or "").strip()
        if not trigger:
            raise ValueError("cron learning jobs require a 'trigger' in payload")
        metadata = dict(job.payload.get("metadata") or {})
        # For built-in daily reflect jobs: compute target dates when omitted.
        if trigger == "dream" and "target_date" not in metadata:
            metadata["target_date"] = (date_type.today() - timedelta(days=1)).isoformat()
        if trigger == "dream" and "diary_target_date" not in metadata:
            metadata["diary_target_date"] = (date_type.today() - timedelta(days=1)).isoformat()
        if trigger == "diary" and "target_date" not in metadata:
            metadata["target_date"] = (date_type.today() - timedelta(days=1)).isoformat()
        summary = str(job.payload.get("summary") or f"cron {trigger} job")
        learning_job = self.schedule_learning_for_session(
            session_id=session_id,
            trigger=trigger,
            summary=summary,
            metadata=metadata,
            force_new=True,
            start_worker=True,
        )
        return ("success", f"learning job queued: {learning_job.job_id} ({trigger})")

    def _cron_session_for_job(self, job: CronJob) -> Episode | None:
        if job.elephant_id:
            return self.latest_session_for_elephant(job.elephant_id)
        if job.profile_id:
            for session in self._list_sessions():
                if session.personal_model_id == job.profile_id:
                    return session
            return self.start(profile_id=job.profile_id)
        latest = self.latest_session()
        if latest is not None:
            return latest
        return self.start(profile_id=self.current_profile().state.profile_id)

    def has_due_cron_jobs(self, *, session_id: str) -> bool:
        session = self._load_session(session_id)
        loaded = self._load_profile(session.personal_model_id)
        return bool(self.cron_runtime.due_jobs(profile_id=loaded.state.profile_id, elephant_id=self.elephant_id_for_session(session)))

    def skill_catalog(self, *, session_id: str | None = None) -> tuple[SkillDefinition, ...]:
        if session_id is not None:
            self.prepare_session_surface(session_id, steady_embeddings=False)
        return self.skill_runtime.catalog.list()
    def list_skill_hub(self, *, limit: int | None = None) -> tuple[SkillHubEntry, ...]:
        entries = self.skill_hub.list(self._current_skill_enabled_overrides())
        if limit is None or limit <= 0:
            return entries
        return entries[:limit]

    def search_skill_hub(self, query: str, *, limit: int = 12) -> tuple[SkillHubEntry, ...]:
        return self.skill_hub.search(query, limit=limit, enabled_overrides=self._current_skill_enabled_overrides())
    def search_skill_sources(self, query: str, *, source: str | None = None, limit: int = 12) -> tuple[SkillSearchEntry, ...]:
        return self.skill_search_hub.search(query, source=source, limit=limit)
    def inspect_experiences(self, *, session_id: str | None = None, profile_id: str | None = None, statuses: tuple[str, ...] = (), limit: int | None = None) -> tuple[ExperienceRecord, ...]:
        return _inspect_experiences(self, session_id=session_id, profile_id=profile_id, statuses=statuses, limit=limit)

    def inspect_growth(
        self,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> ProgressionProjection:
        return _inspect_growth(self, session_id=session_id, profile_id=profile_id)
    def consume_growth_update(self, *, session_id: str) -> GrowthUpdate | None:
        return self.growth_updates.pop(session_id, None)
    def inspect_growth_transition(self, update: GrowthUpdate, *, session_id: str) -> ProgressionTransition:
        return _inspect_growth_transition(self, update, session_id=session_id)

    def inspect_skill_hub_entry(self, reference: str) -> SkillHubEntry:
        entry = self.skill_hub.resolve(reference, self._current_skill_enabled_overrides())
        if entry is None:
            raise KeyError(reference)
        return entry

    def inspect_skill(self, skill_id: str, *, session_id: str | None = None) -> SkillDefinition:
        if session_id is not None:
            self.prepare_session_surface(session_id)
        skill = self.skill_runtime.catalog.get(skill_id)
        if skill is None:
            entry = self.skill_hub.resolve(skill_id, self._current_skill_enabled_overrides())
            if entry is not None:
                definition = load_skill_package_definition(Path(entry.entry_path))
                metadata = dict(definition.metadata)
                metadata.update(entry.metadata)
                source_descriptor = _source_descriptor_for_hub_entry(entry)
                if source_descriptor is not None:
                    metadata.update(source_descriptor.to_metadata())
                metadata.update(
                    {
                        "installed": entry.source_id in {"elephant-installed", "elephant-authored"},
                        "hub_reference": entry.reference,
                    }
                )
                return replace(definition, enabled=False, metadata=metadata)
            raise KeyError(skill_id)
        metadata = dict(skill.metadata)
        metadata.setdefault("installed", True)
        metadata.setdefault("hub_reference", f"elephant-installed:{skill.skill_id}")
        return replace(skill, metadata=metadata)

    def inspect_skill_source(self, skill_id: str, *, session_id: str | None = None) -> SkillDefinition:
        if session_id is not None: self.prepare_session_surface(session_id)
        try:
            return self.inspect_skill(skill_id)
        except KeyError:
            fetched = self.skill_search_hub.fetch(skill_id)
            if fetched is None:
                raise KeyError(skill_id) from None
            return _remote_skill_definition(fetched)

    def set_skill_enabled(
        self,
        skill_id: str,
        enabled: bool,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillDefinition:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        self._refresh_extensions(profile_id=resolved_profile_id)
        updated = self.skill_runtime.set_enabled(skill_id, enabled)
        self._write_extension_override(
            "skill_overrides",
            skill_id,
            enabled,
            profile_id=resolved_profile_id,
        )
        return updated

    def _current_skill_enabled_overrides(self) -> Mapping[str, bool]:
        loaded = self.current_profile()
        return load_extension_manifest(
            loaded.manifest,
            profile_dir=Path(loaded.profile_dir),
        ).skill_overrides

    def install_skill_manifest(
        self,
        manifest_path: str | Path,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillManifestLoadRecord:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        target_profile = self._load_profile(resolved_profile_id)
        resolved_path = Path(manifest_path).expanduser().resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(resolved_path)
        profile_dir = Path(target_profile.profile_dir)
        manifest = dict(target_profile.manifest)
        extension_manifest = load_extension_manifest(manifest, profile_dir=profile_dir)
        existing_paths = list(extension_manifest.skill_manifest_paths)
        if resolved_path not in existing_paths:
            existing_paths.append(resolved_path)
        manifest["skill_manifests"] = [
            serialize_manifest_path(path, profile_dir=profile_dir)
            for path in existing_paths
        ]
        self._save_extensions_manifest(manifest)
        self._refresh_extensions(profile_id=resolved_profile_id)
        return self._skill_manifest_load_record(resolved_path)

    def install_skill_source(
        self,
        reference: str | Path,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        requester: str | None = "operator",
    ) -> SkillManifestLoadRecord:
        raw = str(reference).strip()
        if not raw:
            raise ValueError("skill install requires a hub id, skill path, or manifest path")
        resolved_requester = _normalized_install_requester(requester)
        self._authorize_write(
            operation="cli.skill.install",
            session_id=session_id,
            description=raw,
            metadata={
                "reference": raw,
                "requester": resolved_requester,
            },
        )
        path_candidate = Path(raw).expanduser()
        if path_candidate.exists():
            resolved_path = path_candidate.resolve()
            if resolved_path.is_dir() or resolved_path.name == "SKILL.md":
                return self._install_skill_package_path(
                    resolved_path,
                    session_id=session_id,
                    profile_id=profile_id,
                    source_bucket="path",
                    source_descriptor=_source_descriptor_for_path(resolved_path),
                    requester=resolved_requester,
                )
            return self.install_skill_manifest(
                resolved_path,
                session_id=session_id,
                profile_id=profile_id,
            )
        entry = self.skill_hub.resolve(raw)
        if entry is not None:
            return self._install_skill_package_path(
                Path(entry.entry_path),
                session_id=session_id,
                profile_id=profile_id,
                source_bucket=entry.source_id,
                source_descriptor=_source_descriptor_for_hub_entry(entry),
                requester=resolved_requester,
            )
        fetched = self.skill_search_hub.fetch(raw)
        if fetched is None:
            raise KeyError(f"skill source was not found: {raw}")
        return self._install_skill_package_path(
            Path(fetched.package_path),
            session_id=session_id,
            profile_id=profile_id,
            source_bucket=fetched.source_id,
            source_descriptor=build_public_skill_source_descriptor(
                source_id=fetched.source_id,
                source_label=fetched.source_label,
                source_reference=fetched.reference,
                install_reference=fetched.install_reference,
                trust_level=fetched.trust_level,
                metadata=fetched.metadata,
            ),
            requester=resolved_requester,
        )

    def create_authored_skill(
        self,
        *,
        skill_id: str,
        display_name: str,
        summary: str,
        instruction_text: str,
        category: str | None = None,
        install: bool = True,
        overwrite: bool = False,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillManifestLoadRecord:
        package_path = write_skill_package(
            self.paths.authored_skills_dir,
            skill_id=skill_id,
            display_name=display_name,
            summary=summary,
            instruction_text=instruction_text,
            category=category,
            overwrite=overwrite,
            source_kind="elephant-authored",
        )
        if install:
            return self._install_skill_package_path(
                package_path,
                session_id=session_id,
                profile_id=profile_id,
                source_bucket="authored",
            )
        manifest = SkillPackageLoader().load(package_path)
        return SkillManifestLoadRecord(
            source_path=manifest.source_path,
            skill_ids=tuple(skill.skill_id for skill in manifest.skills),
            loaded_at=_utc_now(),
            status="written",
            detail="shared Elephant Agent authored skill package",
        )

    def update_authored_skill(
        self,
        skill_id: str,
        *,
        display_name: str | None = None,
        summary: str | None = None,
        instruction_text: str | None = None,
        category: str | None = None,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillManifestLoadRecord:
        skill = self.inspect_skill(skill_id, session_id=session_id)
        entry_path = Path(skill.entry_path).expanduser().resolve()
        authored_root = self.paths.authored_skills_dir.expanduser().resolve()
        if not _path_is_within(entry_path, authored_root):
            raise ValueError(f"only authored skills can be updated through tool.skill.manage: {skill_id}")
        current = load_skill_package_definition(entry_path)
        resolved_category = category
        if resolved_category is None:
            try:
                relative = entry_path.parent.relative_to(authored_root)
            except ValueError:
                relative = Path()
            parents = relative.parts[:-1]
            resolved_category = parents[0] if parents else None
        return self.create_authored_skill(
            skill_id=current.skill_id,
            display_name=display_name or current.display_name,
            summary=summary or current.summary,
            instruction_text=instruction_text or current.instruction_text,
            category=resolved_category,
            install=True,
            overwrite=True,
            session_id=session_id,
            profile_id=profile_id,
        )

    def delete_skill_source(
        self,
        skill_id: str,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> tuple[str, str]:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        skill = self.inspect_skill(skill_id, session_id=session_id)
        entry_path = Path(skill.entry_path).expanduser().resolve()
        installed_root = self.paths.installed_skills_dir.expanduser().resolve()
        authored_root = self.paths.authored_skills_dir.expanduser().resolve()
        if not (_path_is_within(entry_path, installed_root) or _path_is_within(entry_path, authored_root)):
            raise ValueError(f"only installed or authored skills can be deleted from this surface: {skill_id}")
        target_profile = self._load_profile(resolved_profile_id)
        profile_dir = Path(target_profile.profile_dir)
        manifest = dict(target_profile.manifest)
        extension_manifest = load_extension_manifest(manifest, profile_dir=profile_dir)
        removed_path = entry_path
        manifest["skill_packages"] = [
            serialize_manifest_path(path, profile_dir=profile_dir)
            for path in extension_manifest.skill_package_paths
            if path.resolve() != removed_path
        ]
        existing_overrides = manifest.get("skill_overrides", {})
        overrides = dict(existing_overrides) if isinstance(existing_overrides, Mapping) else {}
        overrides.pop(skill.skill_id, None)
        if overrides:
            manifest["skill_overrides"] = overrides
        else:
            manifest.pop("skill_overrides", None)
        self._save_extensions_manifest(manifest)
        skill_dir = removed_path.parent
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        self._refresh_extensions(profile_id=resolved_profile_id)
        return skill.skill_id, str(removed_path)

    def create_experience_skill(
        self,
        *,
        skill_id: str,
        display_name: str,
        summary: str,
        instruction_text: str,
        category: str | None = None,
        install: bool = True,
        overwrite: bool = False,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillManifestLoadRecord:
        package_path = write_skill_package(
            self.paths.authored_skills_dir,
            skill_id=skill_id,
            display_name=display_name,
            summary=summary,
            instruction_text=instruction_text,
            category=category or "experience",
            overwrite=overwrite,
        )
        if install:
            return self._install_skill_package_path(
                package_path,
                session_id=session_id,
                profile_id=profile_id,
            )
        manifest = SkillPackageLoader().load(package_path)
        return SkillManifestLoadRecord(
            source_path=manifest.source_path,
            skill_ids=tuple(skill.skill_id for skill in manifest.skills),
            loaded_at=_utc_now(),
            status="written",
            detail="shared Elephant Agent experience skill package",
        )

    def _resolve_extension_profile_id(
        self,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> str:
        if session_id is not None:
            return self._load_session(session_id).personal_model_id
        if profile_id is not None:
            return profile_id
        return self.current_profile().state.profile_id

    def _install_skill_package_path(
        self,
        package_path: Path,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        source_bucket: str | None = None,
        source_descriptor: PublicSkillSourceDescriptor | None = None,
        requester: str | None = "operator",
    ) -> SkillManifestLoadRecord:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        target_profile = self._load_profile(resolved_profile_id)
        resolved_path = package_path.expanduser().resolve()
        if resolved_path.is_dir():
            resolved_path = resolved_path / "SKILL.md"
        if not resolved_path.exists():
            raise FileNotFoundError(resolved_path)
        installed_root = self.paths.installed_skills_dir
        authored_root = self.paths.authored_skills_dir
        definition = load_skill_package_definition(resolved_path)
        source_descriptor = source_descriptor or public_skill_source_descriptor_from_metadata(definition.metadata)
        if (
            source_descriptor is None
            and not _path_is_within(resolved_path, installed_root)
            and not _path_is_within(resolved_path, authored_root)
        ):
            source_descriptor = _source_descriptor_for_path(resolved_path, source_bucket=source_bucket)
        profile_dir = Path(target_profile.profile_dir)
        manifest = dict(target_profile.manifest)
        extension_manifest = load_extension_manifest(manifest, profile_dir=profile_dir)
        existing_paths = list(extension_manifest.skill_package_paths)
        existing_records = [
            record
            for path in existing_paths
            if (record := _installed_skill_record(path)) is not None and record["skill_id"] == definition.skill_id
        ]
        matching_record = _matching_install_record(
            existing_records,
            source_descriptor=source_descriptor,
            selection_path=resolved_path,
        )
        install_action = "install"
        previous_install_reference: str | None = None
        if existing_records:
            install_action = "refresh" if matching_record is not None else "migrate"
            if install_action == "migrate":
                previous_install_reference = _record_install_reference(existing_records[0])
        installed_at = _utc_now().isoformat()
        install_provenance = None
        if source_descriptor is not None:
            install_provenance = build_installed_skill_provenance(
                source=source_descriptor,
                install_action=install_action,
                installed_at=installed_at,
                install_requester=_normalized_install_requester(requester),
                previous_install_reference=previous_install_reference,
            )
        if _path_is_within(resolved_path, installed_root) or _path_is_within(resolved_path, authored_root):
            materialized_path = resolved_path
        else:
            materialized_dir = materialize_skill_package(
                installed_root,
                resolved_path,
                source_bucket=(
                    install_bucket_for_source_descriptor(source_descriptor)
                    if source_descriptor is not None
                    else source_bucket or "imported"
                ),
                install_provenance=install_provenance,
            )
            materialized_path = (materialized_dir / "SKILL.md").resolve()
        stale_paths = {
            Path(record["path"]).expanduser().resolve()
            for record in existing_records
            if Path(record["path"]).expanduser().resolve() != materialized_path
        }
        retained_paths: list[Path] = []
        retained_resolved: set[Path] = set()
        for path in existing_paths:
            resolved_existing = path.expanduser().resolve()
            if resolved_existing in stale_paths:
                continue
            if resolved_existing in retained_resolved:
                continue
            retained_paths.append(resolved_existing)
            retained_resolved.add(resolved_existing)
        if materialized_path not in retained_resolved:
            retained_paths.append(materialized_path)
        manifest["skill_packages"] = [
            serialize_manifest_path(path, profile_dir=profile_dir)
            for path in retained_paths
        ]
        self._save_extensions_manifest(manifest)
        for stale_path in stale_paths:
            if not _path_is_within(stale_path, installed_root):
                continue
            stale_dir = stale_path.parent if stale_path.name == "SKILL.md" else stale_path
            if stale_dir.exists():
                shutil.rmtree(stale_dir, ignore_errors=True)
        self._refresh_extensions(profile_id=resolved_profile_id)
        record = self._skill_manifest_load_record(materialized_path)
        record_metadata = dict(record.metadata)
        if install_provenance is not None:
            record_metadata.update(install_provenance.to_metadata())
        return replace(
            record,
            detail=_install_record_detail(
                source_descriptor=source_descriptor,
                install_action=install_action,
                previous_install_reference=previous_install_reference,
            ),
            metadata=record_metadata,
        )

    def _cron_scope(self, session_id: str) -> tuple[str, str]:
        session = self._load_session(session_id)
        return session.personal_model_id, self.elephant_id_for_session(session)

    def _refresh_extensions(self, *, profile_id: str | None = None) -> None:
        if profile_id is None:
            loaded = self.current_profile()
        else:
            loaded = self._load_profile(profile_id)
        manifest_payload, removed_manifest_keys = sanitize_extension_manifest_payload(dict(loaded.manifest))
        if removed_manifest_keys:
            self._save_extensions_manifest(manifest_payload)
        self._apply_extension_manifest(
            load_extension_manifest(manifest_payload, profile_dir=Path(loaded.profile_dir))
        )

    def _sync_global_custom_mcp_tools(self) -> None:
        config_path = global_config_path_for_state_dir(self.paths.state_dir)
        config = load_global_config(
            config_path,
            state_dir=self.paths.state_dir,
        )
        sync_custom_mcp_tools(
            self.tool_runtime,
            config_path=config_path,
            config=config,
            cwd=Path.cwd(),
        )

    def _apply_extension_manifest(self, manifest: CliExtensionManifest) -> None:
        def _elephant_file_root_for_session(session_id: str | None) -> Path:
            session = self.repository.load_episode_state(session_id) if session_id else None
            if session is not None and session.elephant_id:
                elephant_files = self.paths.elephant_file_path(session.elephant_id)
                elephant_files.mkdir(parents=True, exist_ok=True)
                return elephant_files
            return Path.cwd()
        embedding_service = self.recall_runtime.retriever.evidence_retriever.embedding_service
        semantic_summary_indexer = None
        if self.semantic_index_bundle is not None and embedding_service is not None:
            from packages.evidence import SemanticSummaryIndexer

            # Resolve provider/model from embedding registry for indexing
            _idx_provider_id = ""
            _idx_model_id = ""
            _registry = getattr(embedding_service, "registry", None)
            if _registry is not None:
                _default_model = _registry.default()
                if _default_model is not None:
                    _idx_provider_id = getattr(_default_model, "provider_id", "")
                    _idx_model_id = getattr(_default_model, "model_id", "")
            semantic_summary_indexer = SemanticSummaryIndexer(
                semantic_index=self.semantic_index_bundle.service,
                embedding_service=embedding_service,
                repository=self.repository,
                provider_id=_idx_provider_id,
                model_id=_idx_model_id,
            )
        object.__setattr__(
            self,
            "tool_runtime",
            build_tool_runtime(
                manifest,
                repository=self.repository,
                dependencies=BuiltinToolDependencies(
                    cwd=Path.cwd(),
                    cwd_resolver=_elephant_file_root_for_session,
                    cron_runtime=self.cron_runtime,
                    message_delivery=getattr(self, "message_delivery_surface", None),
                    personal_model_understanding=PersonalModelUnderstandingSurface(
                        repository=self.repository,
                        semantic_summary_indexer=semantic_summary_indexer,
                        semantic_searcher=(
                            self.semantic_index_bundle.searcher
                            if self.semantic_index_bundle is not None
                            else None
                        ),
                        embedding_service=embedding_service,
                    ),
                    skill_management=self,
                    learning_result_surface=self,
                    diary_surface=self,
                    sub_agents_surface=self,
                    todo_store=self.todo_store,
                    browser_backend=self.browser_backend,
                    clarify_surface=self.clarify_surface or StructuredClarifySurface(surface_label="cli"),
                ),
                snapshot_path=self.snapshot_path,
                security_policy=self.security_policy,
            ),
        )
        self._sync_global_custom_mcp_tools()
        self.model_provider.tool_runtime = self.tool_runtime
        object.__setattr__(
            self,
            "skill_runtime",
            build_skill_runtime(
                manifest,
                repository=self.repository,
                profile_loader=self.profile_loader,
            ),
        )

    def _tool_manifest_load_record(self, manifest_path: Path) -> ToolManifestLoadRecord:
        for record in reversed(self.tool_runtime.list_manifest_loads()):
            if Path(record.source_path) == manifest_path:
                return record
        raise LookupError(f"tool manifest was not loaded: {manifest_path}")

    def _skill_manifest_load_record(self, manifest_path: Path) -> SkillManifestLoadRecord:
        for record in reversed(self.skill_runtime.list_manifest_loads()):
            if Path(record.source_path) == manifest_path:
                return record
        raise LookupError(f"skill manifest was not loaded: {manifest_path}")

    def _write_extension_override(
        self,
        section: str,
        item_id: str,
        enabled: bool,
        *,
        profile_id: str | None = None,
    ) -> None:
        loaded = self.current_profile() if profile_id is None else self._load_profile(profile_id)
        profile_dir = Path(loaded.profile_dir)
        manifest = dict(loaded.manifest)
        existing = manifest.get(section, {})
        overrides = dict(existing) if isinstance(existing, Mapping) else {}
        overrides[item_id] = {"enabled": enabled}
        manifest[section] = overrides
        self._save_extensions_manifest(manifest)
