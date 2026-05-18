"""Loop execution and HTTP dispatch methods for the API runtime app."""

from __future__ import annotations

from dataclasses import replace
import re
import shutil
from typing import Any, Mapping
from urllib.parse import unquote
from uuid import uuid4

from packages.context import (
    next_session_context_epoch,
)
from packages.context.epoch_store import FileEpochStore
from packages.contracts import EventEnvelope
from packages.kernel import KernelSourceRequest, ReconciliationPipeline, StateReconciler
from packages.operator.runtime import RecallEvidenceOperatorDetail
from packages.runtime_layout import elephant_file_path
from packages.state import render_default_elephant_identity, write_elephant_identity_file

from .api_runtime_support import (
    APILoopRecord,
    APILoopResult,
    APIResponse,
    _jsonable,
    _now,
    _optional_str,
    _read_json_bytes,
    _split_path,
)
from .api_runtime_http_dispatch_helpers import (
    _cron_job_system_kind,
    _elephant_id_from_name,
    _cron_payload,
    _cron_skill_ids,
    _cron_job_record,
    _read_wsgi_body,
)

def run_loop(
    self,
    episode_id: str,
    *,
    prompt: str,
    state_query: str | None = None,
    tool_name: str | None = None,
    tool_arguments: Mapping[str, Any] | None = None,
    delivery_payload: Mapping[str, Any] | None = None,
) -> APILoopResult:
    episode = self.repository.load_episode_state(episode_id)
    if episode is None:
        raise KeyError(episode_id)
    if episode.status == "closed":
        raise ValueError(f"cannot send to a closed episode: {episode_id}")
    personal_model = self.repository.load_personal_model_runtime_state(episode.personal_model_id)
    if personal_model is None:
        raise KeyError(episode.personal_model_id)
    stored_episode = self.repository.load_episode(episode_id)
    route_state = self.repository.load_state(stored_episode.state_id) if stored_episode is not None else None
    event = EventEnvelope(
        event_id=f"api:{episode_id}:loop:{uuid4().hex}",
        event_type="loop.received",
        episode_id=episode_id,
        source="api",
        payload={
            "message": prompt,
            "content": prompt,
            "summary": prompt,
            "state_query": state_query or "",
            "tool_name": tool_name or "",
        },
    )
    outcome = self.kernel.run(
        KernelSourceRequest(
            route_id=episode_id,
            prompt=prompt,
            surface="api",
            source_event_type="loop.received",
            source_payload=dict(event.payload),
            source_event_id=event.event_id,
            route_profile_id=episode.personal_model_id,
            route_status=episode.status,
            route_interruption_state=episode.interruption_state,
            route_started_at=episode.started_at,
            personal_model_id=route_state.personal_model_id if route_state is not None else episode.personal_model_id,
            state_id=route_state.state_id if route_state is not None else None,
            episode_id=episode.episode_id,
            episode_policy="api_session",
            state_query=state_query,
            tool_name=tool_name,
            tool_arguments=dict(tool_arguments or {}),
            delivery_payload=dict(delivery_payload or {}),
        )
    )
    observation = ReconciliationPipeline().observe_turn(
        inbound_event=event,
        execution=outcome.execution,
        decision_summary=outcome.state.summary or outcome.execution.summary,
        source="api",
        profile_id=episode.personal_model_id,
        elephant_id=episode.elephant_id,
        turn_messages=outcome.turn_messages,
    )
    StateReconciler().reconcile_turn(
        repository=self.repository,
        recall_runtime=self.recall_runtime,
        observation=observation,
    )
    _epoch_store = FileEpochStore(self.repository.database_path.parent)
    existing_epoch = _epoch_store.load(episode.episode_id)
    updated_epoch = next_session_context_epoch(
        existing_epoch,
        session=episode,
        event=outcome.event,
        execution=outcome.execution,
        context=outcome.context,
        turn_messages=outcome.turn_messages,
        thread_focus=outcome.state.summary,
    )
    if updated_epoch != existing_epoch:
        _epoch_store.save(updated_epoch)
    record = APILoopRecord(
        request={
            "prompt": prompt,
            "state_query": state_query,
            "tool_name": tool_name,
            "tool_arguments": dict(tool_arguments or {}),
            "delivery_payload": dict(delivery_payload or {}),
        },
        outcome=outcome,
        recorded_at=_now(),
    )
    self._loops.setdefault(episode_id, []).append(record)
    inspection = self.inspect_episode(episode_id)
    return APILoopResult(
        episode=inspection.episode,
        outcome=outcome,
        latest_loop=record,
        inspection=inspection,
    )
def dispatch(self, method: str, path: str, body: bytes | None = None) -> APIResponse:
    if method.upper() == "GET" and path == "/healthz":
        return APIResponse(200, {"status": "ok", "service": "elephant-api"})

    try:
        parts = _split_path(path)
        if not parts:
            return APIResponse(404, {"error": "not_found"})
        if parts[0] == "providers":
            return self._dispatch_providers(method, parts[1:], body)
        if parts[0] == "internal":
            return self._dispatch_internal(method, parts[1:], body)
        if parts[0] == "operator":
            return self._dispatch_operator(method, parts[1:], body)
        if parts[0] == "herd":
            return _dispatch_elephants(self, method, parts[1:], body)
        if parts[0] == "episodes":
            return self._dispatch_episodes(method, parts[1:], body)
        if parts[0] == "states":
            return self._dispatch_states(method, parts[1:], body)
        return APIResponse(404, {"error": "not_found"})
    except KeyError as error:
        return APIResponse(404, {"error": "not_found", "missing": str(error)})
    except (ValueError, TypeError) as error:
        return APIResponse(400, {"error": "bad_request", "detail": str(error)})
    except LookupError as error:
        return APIResponse(422, {"error": "configuration_required", "detail": str(error)})
    except Exception as error:
        return APIResponse(500, {"error": "internal_error", "detail": str(error)})
def _unique_elephant_id(self, base_elephant_id: str) -> str:
    root = _elephant_id_from_name(base_elephant_id)
    elephant_id = root
    suffix = 2
    while _elephant_state_for_id(self, elephant_id) is not None:
        elephant_id = f"{root}-{suffix}"
        suffix += 1
    return elephant_id
def _elephant_state_for_id(self, elephant_id: str):
    target = elephant_id.strip()
    if not target:
        return None
    direct = self.repository.load_state(f"state:{target}")
    if direct is not None:
        return direct
    return next((state for state in self.repository.list_states() if state.elephant_id == target), None)
def _default_elephant_identity_text(*, elephant_id: str, display_name: str, mode: str) -> str:
    """Seed identity text when none is supplied via the API.

    Mirrors the CLI's first-person self-introduction template so a
    companion created through the API reads the same way a CLI-created
    companion does. Internal metadata (id, mode) lives in an HTML
    comment so it stays out of the prompt.
    """
    charter = render_default_elephant_identity(
        display_name=display_name,
        personality_preset=None,
        initiative="gentle",
        mode=mode,
    )
    return "\n".join(
        (
            f"<!-- Internal metadata (not shown to the model). id: {elephant_id}. mode: {mode}. "
            f"Edit the paragraphs below to reshape how {display_name} introduces themselves. -->",
            "",
            charter,
        )
    )
def _elephant_identity_text_from_payload(payload: Mapping[str, Any], *, elephant_id: str, display_name: str, mode: str) -> str:
    return (
        _optional_str(payload.get("elephant_identity_text") or payload.get("eggIdentityText") or payload.get("text") or payload.get("content"))
        or _default_elephant_identity_text(elephant_id=elephant_id, display_name=display_name, mode=mode)
    )
def _write_elephant_identity_file(self, *, elephant_id: str, text: str) -> str:
    path = write_elephant_identity_file(
        elephant_file_path(elephant_id, install_root=self.config.install_root),
        text,
    )
    return str(path)
def _dispatch_elephants(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    normalized_method = method.upper()
    if normalized_method == "POST" and not parts:
        payload = _read_json_bytes(body)
        display_name = str(payload.get("elephant_name") or payload.get("display_name") or payload.get("name") or "").strip()
        if not display_name:
            raise ValueError("display_name is required")
        raw_elephant_id = str(payload.get("elephant_id") or payload.get("eggId") or "").strip()
        if raw_elephant_id and _elephant_state_for_id(self, raw_elephant_id) is not None:
            raise ValueError(f"elephant already exists: {raw_elephant_id}")
        elephant_id = raw_elephant_id or _unique_elephant_id(self, display_name)
        mode = str(payload.get("mode") or "companion").strip() or "companion"
        personal_model_id = str(
            payload.get("personal_model_id")
            or payload.get("profile_id")
            or self.repository.ensure_default_personal_model().personal_model_id
        ).strip()
        identity_text = _elephant_identity_text_from_payload(payload, elephant_id=elephant_id, display_name=display_name, mode=mode)
        state = self.repository.create_state(
            personal_model_id=personal_model_id,
            state_id=f"state:{elephant_id}",
            state_anchor=f"elephant:{elephant_id}",
            elephant_id=elephant_id,
            elephant_name=display_name,
            identity_mode=mode,
            initiative=_optional_str(payload.get("initiative")) or "",
            working_style=_optional_str(payload.get("personality_preset") or payload.get("working_style")) or "",
            surface_bindings=("api", "dashboard"),
            elephant_identity_text=identity_text,
            summary=f"{display_name} is ready to continue this elephant line.",
            metadata={"profile_id": personal_model_id},
        )
        elephant_identity_path = _write_elephant_identity_file(self, elephant_id=elephant_id, text=identity_text)
        return APIResponse(201, _jsonable({"elephant": state, "eggIdentityPath": elephant_identity_path}))
    if len(parts) != 1:
        return APIResponse(404, {"error": "not_found"})
    elephant_id = unquote(parts[0]).strip()
    state = _elephant_state_for_id(self, elephant_id)
    if state is None:
        raise KeyError(elephant_id)
    if normalized_method in {"PATCH", "POST"}:
        payload = _read_json_bytes(body)
        display_name = _optional_str(payload.get("elephant_name") or payload.get("display_name") or payload.get("name"))
        mode = _optional_str(payload.get("mode"))
        identity_text = _optional_str(payload.get("elephant_identity_text") or payload.get("eggIdentityText") or payload.get("text") or payload.get("content"))
        updated = replace(
            state,
            elephant_name=display_name or state.elephant_name,
            identity_mode=mode or state.identity_mode or "companion",
            initiative=_optional_str(payload.get("initiative")) if payload.get("initiative") is not None else state.initiative,
            working_style=(
                _optional_str(payload.get("personality_preset") or payload.get("working_style"))
                if payload.get("personality_preset") is not None or payload.get("working_style") is not None
                else state.working_style
            ),
            elephant_identity_text=identity_text if identity_text is not None else state.elephant_identity_text,
            summary=f"{display_name or state.elephant_name} is ready to continue this elephant line.",
            metadata={**dict(state.metadata), "profile_id": state.personal_model_id},
        )
        self.repository.upsert_state(updated)
        elephant_identity_path = ""
        if identity_text is not None:
            elephant_identity_path = _write_elephant_identity_file(self, elephant_id=updated.elephant_id, text=identity_text)
        return APIResponse(200, _jsonable({"elephant": updated, "eggIdentityPath": elephant_identity_path}))
    if normalized_method == "DELETE":
        episode_ids = tuple(episode.episode_id for episode in self.repository.list_episodes(state_id=state.state_id))
        deleted_sessions = self.repository.delete_episodes(episode_ids, delete_orphaned_profiles=False)
        self.repository.delete_state(state.state_id)
        shutil.rmtree(elephant_file_path(state.elephant_id, install_root=self.config.install_root), ignore_errors=True)
        return APIResponse(200, _jsonable({"elephant_id": state.elephant_id, "deleted": True, "deleted_sessions": deleted_sessions}))
    return APIResponse(404, {"error": "not_found"})
def _dispatch_episodes(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    if method.upper() == "POST" and len(parts) == 0:
        payload = _read_json_bytes(body)
        result = self.create_episode(
            personal_model_id=str(payload.get("personal_model_id") or payload["profile_id"]),
            display_name=str(payload["display_name"]),
            mode=str(payload["mode"]),
            elephant_id=payload.get("elephant_id"),
            elephant_path=payload.get("elephant_path"),
            preferences=tuple(payload.get("preferences", ())),
            enabled_capabilities=tuple(payload.get("enabled_capabilities", ())),
            provider_profile=payload.get("provider_profile"),
            episode_id=payload.get("episode_id"),
        )
        return APIResponse(201, _jsonable(result.to_record()))
    if len(parts) < 1:
        return APIResponse(404, {"error": "not_found"})
    episode_id = parts[0]
    if method.upper() == "GET" and len(parts) == 1:
        return APIResponse(200, _jsonable(self.inspect_episode(episode_id).to_record()))
    if method.upper() == "POST" and len(parts) == 2 and parts[1] == "interrupt":
        payload = _read_json_bytes(body)
        result = self.interrupt_episode(episode_id, interruption_state=str(payload["interruption_state"]))
        return APIResponse(200, _jsonable(result.to_record()))
    if method.upper() == "POST" and len(parts) == 2 and parts[1] == "next":
        payload = _read_json_bytes(body)
        result = self.open_next_episode(episode_id, child_episode_id=payload.get("child_episode_id"))
        return APIResponse(200, _jsonable(result.to_record()))
    if method.upper() == "POST" and len(parts) == 2 and parts[1] == "loops":
        payload = _read_json_bytes(body)
        result = self.run_loop(
            episode_id,
            prompt=str(payload["prompt"]),
            state_query=payload.get("state_query"),
            tool_name=payload.get("tool_name"),
            tool_arguments=payload.get("tool_arguments"),
            delivery_payload=payload.get("delivery_payload"),
        )
        return APIResponse(200, _jsonable(result.to_record()))
    if method.upper() == "GET" and len(parts) == 2 and parts[1] == "profile":
        inspection = self.inspect_episode(episode_id)
        return APIResponse(200, _jsonable({"personal_model": inspection.personal_model}))
    if len(parts) == 2 and parts[1] in {"identity", "user", "relationship", "continuity"}:
        episode = self.repository.load_episode(episode_id)
        if episode is None:
            raise KeyError(episode_id)
        return self._dispatch_states(method, (episode.state_id, parts[1]), body)
    if len(parts) == 2 and parts[1] == "recall":
        if method.upper() == "GET":
            return APIResponse(200, _jsonable({"episode_id": episode_id, "recall": self.inspect_recall_evidence_surface(episode_id)}))
    if len(parts) == 3 and parts[1] == "recall" and parts[2] == "evidence":
        if method.upper() == "GET":
            return APIResponse(200, _jsonable({"episode_id": episode_id, "evidence": self.list_recall_evidence(episode_id)}))
    if len(parts) == 3 and parts[1] == "recall" and parts[2] == "search":
        payload = _read_json_bytes(body)
        query = _optional_str(payload.get("query"))
        if query is None:
            raise ValueError("recall search query is required")
        limit = int(payload.get("limit", 5))
        return APIResponse(
            200,
            _jsonable({
                "episode_id": episode_id,
                "recall": self.search_recall_evidence_surface(episode_id, query=query, limit=limit),
            }),
        )
    if len(parts) == 3 and parts[1] == "recall":
        evidence_ref = parts[2]
        if method.upper() == "GET":
            detail = self.inspect_recall_evidence(episode_id, evidence_ref)
            return APIResponse(
                200,
                _jsonable(
                    {
                        "episode_id": episode_id,
                        "evidence": RecallEvidenceOperatorDetail(
                            evidence=detail["evidence"],
                            state=detail["state"],
                            lineage=detail["lineage"],
                        ),
                    }
                ),
            )
    return APIResponse(404, {"error": "not_found"})
def _dispatch_states(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    if len(parts) != 2:
        return APIResponse(404, {"error": "not_found"})
    state_id, surface = parts
    if surface == "identity":
        if method.upper() == "GET":
            return APIResponse(200, _jsonable({"state_id": state_id, "identity": self.inspect_identity(state_id=state_id)}))
        if method.upper() in {"PATCH", "POST"}:
            payload = _read_json_bytes(body)
            result = self.update_identity_state(
                state_id=state_id,
                display_name=_optional_str(payload.get("display_name") or payload.get("name")),
                personality_preset=_optional_str(payload.get("personality_preset")),
                initiative=_optional_str(payload.get("initiative")),
                elephant_identity_text=_optional_str(payload.get("elephant_identity_text") or payload.get("eggIdentityText") or payload.get("text") or payload.get("content")),
                clear_elephant_identity=bool(payload.get("clear_elephant_identity", False)),
            )
            return APIResponse(200, _jsonable({"state_id": state_id, "identity": result}))
    if surface == "user":
        if method.upper() == "GET":
            return APIResponse(200, _jsonable({"state_id": state_id, "user": self.inspect_user(state_id=state_id)}))
        if method.upper() in {"PATCH", "POST"}:
            payload = _read_json_bytes(body)
            result = self.update_user_state(
                state_id=state_id,
                text=_optional_str(payload.get("text") or payload.get("content")),
                fields=payload.get("fields") if isinstance(payload.get("fields"), dict) else None,
                append=bool(payload.get("append", False)),
                clear=bool(payload.get("clear", False)),
            )
            return APIResponse(200, _jsonable({"state_id": state_id, "user": result}))
    if surface == "relationship":
        if method.upper() == "GET":
            return APIResponse(200, _jsonable({"state_id": state_id, "relationship": self.inspect_relationship(state_id=state_id)}))
        if method.upper() in {"PATCH", "POST"}:
            payload = _read_json_bytes(body)
            result = self.update_relationship_state(
                state_id=state_id,
                text=_optional_str(payload.get("text") or payload.get("content")),
                append=bool(payload.get("append", False)),
                clear=bool(payload.get("clear", False)),
            )
            return APIResponse(200, _jsonable({"state_id": state_id, "relationship": result}))
    if surface == "continuity" and method.upper() == "GET":
        return APIResponse(200, _jsonable(self.inspect_continuity(state_id).to_record()))
    return APIResponse(404, {"error": "not_found"})
def _dispatch_providers(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    if method.upper() == "GET" and len(parts) == 0:
        return APIResponse(200, _jsonable(self.list_providers()))
    if method.upper() == "GET" and len(parts) == 1 and parts[0] == "doctor":
        return APIResponse(200, _jsonable(self.doctor_provider()))
    if method.upper() == "GET" and len(parts) == 2 and parts[0] == "setup":
        return APIResponse(200, _jsonable(self.setup_provider(parts[1])))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "models":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.discover_provider_models(payload)))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "default":
        payload = _read_json_bytes(body)
        provider_profile = payload.get("provider_profile")
        if not isinstance(provider_profile, dict):
            raise ValueError("provider_profile must be an object describing the default provider configuration")
        result = self.set_default_provider(provider_profile)
        return APIResponse(200, _jsonable(result))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "test":
        payload = _read_json_bytes(body)
        result = self.test_provider(prompt=str(payload.get("prompt", "Summarize the current provider configuration.")))
        return APIResponse(200, _jsonable(result))
    if method.upper() == "GET" and len(parts) == 1 and parts[0] == "embeddings":
        return APIResponse(200, _jsonable({"embedding_provider": self.embedding_provider_summary()}))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "embeddings":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.set_embedding_provider(payload)))
    if method.upper() == "GET" and len(parts) == 1 and parts[0] == "keys":
        return APIResponse(200, _jsonable(self.list_provider_keys()))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "keys":
        payload = _read_json_bytes(body)
        return APIResponse(201, _jsonable(self.create_provider_key(payload)))
    if method.upper() == "PATCH" and len(parts) == 2 and parts[0] == "keys":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.upsert_provider_key(parts[1], payload)))
    if method.upper() == "DELETE" and len(parts) == 2 and parts[0] == "keys":
        return APIResponse(200, _jsonable(self.delete_provider_key(parts[1])))
    return APIResponse(404, {"error": "not_found"})

def _dispatch_internal(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    if method.upper() == "GET" and len(parts) == 2 and parts[0] == "dashboard":
        return APIResponse(200, {"dashboard": _jsonable(self.inspect_internal_dashboard(parts[1]))})
    if method.upper() == "POST" and len(parts) == 2 and parts[0] == "diary" and parts[1] == "write":
        payload = _read_json_bytes(body)
        target_date = str(payload.get("date") or "").strip()
        if not target_date:
            return APIResponse(400, {"error": "date is required (YYYY-MM-DD)"})
        result = self.trigger_diary_write(target_date=target_date)
        return APIResponse(200, _jsonable(result))
    if method.upper() == "DELETE" and len(parts) == 2 and parts[0] == "diary":
        try:
            result = self.delete_diary_entry(entry_date=unquote(parts[1]))
        except ValueError as error:
            return APIResponse(400, {"error": str(error)})
        return APIResponse(200, _jsonable(result))
    if method.upper() == "POST" and len(parts) == 2 and parts[0] == "reflect" and parts[1] == "run":
        payload = _read_json_bytes(body)
        trigger = str(payload.get("trigger") or "manual").strip()
        features = str(payload.get("features") or "").strip() or None
        result = self.trigger_reflect_job(trigger=trigger, features=features)
        return APIResponse(200, _jsonable(result))
    return APIResponse(404, {"error": "not_found"})

def _dispatch_operator(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    if parts and parts[0] == "cron":
        if method.upper() == "GET" and len(parts) == 1:
            return APIResponse(200, {"cron": {"jobs": [_cron_job_record(job) for job in self.cron_runtime.list_jobs()]}})
        if method.upper() == "POST" and len(parts) == 1:
            payload = _read_json_bytes(body)
            job_payload = _cron_payload(payload)
            job = self.cron_runtime.create_job(
                name=str(payload.get("name") or "Elephant Agent job"),
                schedule_text=str(payload["schedule"]),
                payload=job_payload,
                profile_id=_optional_str(payload.get("profile_id")),
                elephant_id=_optional_str(payload.get("elephant_id")),
                timezone_name=_optional_str(payload.get("timezone_name")),
            )
            return APIResponse(201, {"cron": {"job": _cron_job_record(job)}})
        if len(parts) == 2:
            job_id = parts[1]
            if method.upper() == "GET":
                if job_id == "system:proactive-ask":
                    from .api_runtime_console import _proactive_ask_system_job

                    job = _proactive_ask_system_job(self)
                    if job is None:
                        raise ValueError(f"system cron job unavailable: {job_id}")
                    return APIResponse(200, {"cron": {"job": job}})
                return APIResponse(200, {"cron": {"job": _cron_job_record(self.cron_runtime.inspect_job(job_id))}})
            if method.upper() == "PATCH":
                payload = _read_json_bytes(body)
                action = str(payload.get("action") or "").strip().lower()
                if action == "pause":
                    if job_id == "system:proactive-ask":
                        _persist_proactive_ask_config(self.repository.database_path.parent, {"enabled": False})
                        from .api_runtime_console import _proactive_ask_system_job

                        job = _proactive_ask_system_job(self)
                    else:
                        job = self.cron_runtime.pause_job(job_id)
                elif action == "resume":
                    if job_id == "system:proactive-ask":
                        _persist_proactive_ask_config(self.repository.database_path.parent, {"enabled": True})
                        from .api_runtime_console import _proactive_ask_system_job

                        job = _proactive_ask_system_job(self)
                    else:
                        job = self.cron_runtime.resume_job(job_id)
                else:
                    raise ValueError("cron PATCH requires action=pause or action=resume")
                if job is None:
                    raise ValueError(f"system cron job unavailable: {job_id}")
                return APIResponse(200, {"cron": {"job": job if isinstance(job, Mapping) else _cron_job_record(job)}})
            if method.upper() == "DELETE":
                if job_id == "system:proactive-ask":
                    return APIResponse(403, {"error": "system_cron_jobs_cannot_be_deleted"})
                job = self.cron_runtime.inspect_job(job_id)
                if _cron_job_system_kind(job) is not None:
                    return APIResponse(403, {"error": "system_cron_jobs_cannot_be_deleted"})
                job = self.cron_runtime.remove_job(job_id)
                return APIResponse(200, {"cron": {"job": _cron_job_record(job), "status": "removed"}})
        if len(parts) == 3 and parts[2] == "run" and method.upper() == "POST":
            # Manual-trigger ("Verify") endpoint. Runs the job once right now, goes
            # through the exact same execute → delivery pipeline the scheduler uses,
            # and returns the result synchronously so the dashboard can show it.
            if parts[1] == "system:proactive-ask":
                return APIResponse(200, _jsonable(self.run_proactive_ask_now()))
            return APIResponse(200, _jsonable(self.run_cron_job_now(parts[1])))
    if method.upper() == "PATCH" and len(parts) == 1 and parts[0] == "settings":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.patch_operator_settings(payload)))
    if method.upper() == "PATCH" and len(parts) == 1 and parts[0] == "config":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.patch_operator_global_config(payload)))
    if method.upper() == "POST" and len(parts) == 2 and parts[0] == "mcp" and parts[1] == "discover":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.discover_operator_mcp_server(payload)))
    if len(parts) >= 2 and parts[0] == "mcp" and parts[1] == "servers":
        payload = _read_json_bytes(body)
        if method.upper() in {"POST", "PATCH"} and len(parts) == 2:
            status_code = 200 if method.upper() == "PATCH" else 201
            return APIResponse(status_code, _jsonable(self.sync_operator_mcp_server(payload)))
        if method.upper() == "DELETE" and len(parts) == 2:
            return APIResponse(200, _jsonable(self.delete_operator_mcp_server(payload)))
    if len(parts) >= 2 and parts[0] == "mcp" and parts[1] == "tools":
        payload = _read_json_bytes(body)
        if method.upper() == "POST" and len(parts) == 2:
            return APIResponse(201, _jsonable(self.create_operator_mcp_tool(payload)))
        if method.upper() == "PATCH" and len(parts) == 2:
            return APIResponse(200, _jsonable(self.update_operator_mcp_tool(payload)))
        if method.upper() == "DELETE" and len(parts) == 2:
            return APIResponse(200, _jsonable(self.delete_operator_mcp_tool(payload)))
        if method.upper() == "PATCH" and len(parts) == 3 and parts[2] == "enabled":
            return APIResponse(200, _jsonable(self.set_operator_mcp_tool_enabled(payload)))
    if method.upper() == "POST" and len(parts) == 1 and parts[0] == "gateway":
        payload = _read_json_bytes(body)
        return APIResponse(200, _jsonable(self.gateway_action(payload)))
    if parts and parts[0] == "personal-model":
        return _dispatch_personal_model(self, method, parts[1:], body)
    if method.upper() == "PATCH" and len(parts) == 2 and parts[0] in {"skills", "tools"}:
        payload = _read_json_bytes(body)
        result = self.set_console_item_enabled(
            kind="skill" if parts[0] == "skills" else "tool",
            item_id=parts[1],
            enabled=bool(payload.get("enabled")),
        )
        return APIResponse(200, _jsonable(result))
    return APIResponse(404, {"error": "not_found"})
def _dispatch_personal_model(
    self, method: str, parts: tuple[str, ...], body: bytes | None
) -> APIResponse:
    """Operator-surface writes against Personal Model claims and questions.

    Routes:
      * ``PATCH /v1/operator/personal-model/questions`` — update proactive question cadence.
      * ``POST  /v1/operator/personal-model/questions/{id}/bump``
      * ``POST  /v1/operator/personal-model/questions/{id}/dismiss``
      * ``POST  /v1/operator/personal-model/questions/{id}/answer``
      * ``POST  /v1/operator/personal-model/claims/{id}/correct``
      * ``POST  /v1/operator/personal-model/claims/{id}/forget``
      * ``POST  /v1/operator/personal-model/claims/{id}/restore``
      * ``POST  /v1/operator/personal-model/claims/{id}/delete``
      * ``POST  /v1/operator/personal-model/claims/{id}/protect``
      * ``POST  /v1/operator/personal-model/claims/{id}/unprotect``
    """
    from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID
    from packages.understanding import PersonalModelUnderstandingSurface

    normalized = method.upper()

    if normalized == "PATCH" and parts == ("questions",):
        payload = _read_json_bytes(body)
        # New format: accepts proactive_ask config directly (idle_threshold_minutes, daily_max, quiet_hours).
        # Legacy: also accepts learning_intensity for migration.
        proactive_updates: dict[str, Any] = {}
        if "idle_threshold_minutes" in payload:
            proactive_updates["idle_threshold_minutes"] = max(1, int(payload["idle_threshold_minutes"]))
        if "daily_max" in payload:
            proactive_updates["daily_max"] = max(1, int(payload["daily_max"]))
        if "quiet_hours" in payload:
            qh = payload["quiet_hours"]
            if isinstance(qh, (list, tuple)) and len(qh) == 2:
                proactive_updates["quiet_hours"] = [int(qh[0]) % 24, int(qh[1]) % 24]
        if "enabled" in payload:
            proactive_updates["enabled"] = bool(payload["enabled"])
        # Legacy migration: map learning_intensity → numeric values.
        intensity = str(payload.get("learning_intensity") or "").strip().lower()
        if intensity in {"low", "medium", "high"} and not proactive_updates:
            _INTENSITY_MAP = {
                "low": {"idle_threshold_minutes": 720, "daily_max": 2, "quiet_hours": [23, 7]},
                "medium": {"idle_threshold_minutes": 180, "daily_max": 8, "quiet_hours": [23, 7]},
                "high": {"idle_threshold_minutes": 60, "daily_max": 24, "quiet_hours": [1, 7]},
            }
            proactive_updates = _INTENSITY_MAP[intensity]
        if not proactive_updates:
            raise ValueError("provide idle_threshold_minutes, daily_max, quiet_hours, or learning_intensity")
        _persist_proactive_ask_config(self.repository.database_path.parent, proactive_updates)
        return APIResponse(200, {"proactive_ask": proactive_updates})

    if normalized == "POST" and len(parts) >= 3 and parts[0] == "questions":
        question_id = unquote(parts[1]).strip()
        action = parts[2].strip().lower()
        if action not in {"bump", "dismiss", "answer"}:
            return APIResponse(404, {"error": "not_found"})
        payload = _read_json_bytes(body) if body else {}
        personal_model_id = str(payload.get("personal_model_id") or DEFAULT_PERSONAL_MODEL_ID)
        if action == "bump":
            list_open = getattr(self.repository, "list_open_questions", None)
            upsert = getattr(self.repository, "upsert_open_question", None)
            if not callable(list_open) or not callable(upsert):
                return APIResponse(500, {"error": "personal_model_questions_not_available"})
            candidates = list_open(personal_model_id=personal_model_id, status=("open", "asked"))
            target = next((q for q in candidates if q.question_id == question_id), None)
            if target is None:
                return APIResponse(404, {"error": "question_not_found"})
            bumped = replace(target, priority=min(1.0, max(target.priority, 0.85)))
            upsert(bumped)
            return APIResponse(200, {"personal_model": {"question_id": question_id, "priority": bumped.priority}})
        if action == "dismiss":
            surface = PersonalModelUnderstandingSurface(repository=self.repository, semantic_summary_indexer=getattr(self, "semantic_summary_indexer", None))
            result = surface.manage_personal_model_questions(
                str(payload.get("episode_id") or "dashboard"),
                action="dismiss",
                personal_model_id=personal_model_id,
                question_id=question_id,
                reason=str(payload.get("reason") or "user_opted_out"),
            )
            return APIResponse(200, {"personal_model": result})
        if action == "answer":
            content = str(payload.get("content") or "").strip()
            if not content:
                raise ValueError("answer requires 'content'")
            surface = PersonalModelUnderstandingSurface(repository=self.repository, semantic_summary_indexer=getattr(self, "semantic_summary_indexer", None))
            result = surface.manage_personal_model_questions(
                str(payload.get("episode_id") or "dashboard"),
                action="answer",
                personal_model_id=personal_model_id,
                question_id=question_id,
                answer=content,
                reason="dashboard answer",
            )
            return APIResponse(200, {"personal_model": result})

    if normalized == "POST" and len(parts) >= 3 and parts[0] == "claims":
        claim_id = unquote(parts[1]).strip()
        action = parts[2].strip().lower()
        if action not in {"correct", "forget", "dispute", "restore", "delete", "protect", "unprotect"}:
            return APIResponse(404, {"error": "not_found"})
        payload = _read_json_bytes(body) if body else {}
        personal_model_id = str(payload.get("personal_model_id") or DEFAULT_PERSONAL_MODEL_ID).strip() or DEFAULT_PERSONAL_MODEL_ID
        facts = tuple(self.repository.list_personal_model_facts(personal_model_id=personal_model_id, status=("active", "retired", "disputed") if action in {"restore", "delete"} else "active"))
        target = next((fact for fact in facts if fact.fact_id == claim_id), None)
        if target is None:
            return APIResponse(404, {"error": "claim_not_found"})
        metadata = dict(target.metadata or {})
        reason = str(payload.get("reason") or f"dashboard {action}").strip()
        if action in {"protect", "unprotect"}:
            now = _now()
            if action == "protect":
                next_metadata = {
                    **metadata,
                    "protected": "user",
                    "protected_reason": reason or "dashboard protect",
                    "projection_policy": str(metadata.get("projection_policy") or "tool_only"),
                    "protected_at": now.isoformat(),
                }
            else:
                next_metadata = {
                    **metadata,
                    "protected": "user_unprotected",
                    "protected_reason": reason or "dashboard unprotect",
                    "unprotected_at": now.isoformat(),
                }
            updated = replace(target, metadata=next_metadata)
            self.repository.upsert_personal_model_fact(updated)
            return APIResponse(200, {"personal_model": {"action": action, "status": "active", "ref": claim_id, "claim": _serialize(updated)}})
        if action == "delete":
            from packages.understanding.personal_model_governance import is_protected_topic
            if is_protected_topic(str(metadata.get("topic") or ""), metadata):
                return APIResponse(409, {"error": "protected_topic", "detail": "protected Personal Model topics must be unprotected before delete", "ref": claim_id})
            now = _now()
            deleted = replace(
                target,
                status="deleted",
                metadata={
                    **metadata,
                    "deleted_by": "dashboard",
                    "deleted_reason": reason,
                    "deleted_at": now.isoformat(),
                    "understanding_status": "deleted",
                },
            )
            self.repository.upsert_personal_model_fact(deleted)
            list_entries = getattr(self.repository, "list_semantic_index_entries", None)
            upsert_entry = getattr(self.repository, "upsert_semantic_index_entry", None)
            if callable(list_entries) and callable(upsert_entry):
                for entry in list_entries(personal_model_id=personal_model_id, owner_scope="personal_model"):
                    if getattr(entry, "source_id", "") != claim_id:
                        continue
                    upsert_entry(
                        replace(
                            entry,
                            status="deleted",
                            updated_at=now,
                            metadata={
                                **dict(getattr(entry, "metadata", {}) or {}),
                                "claim_status": "deleted",
                                "deactivated_by": "dashboard",
                            },
                        )
                    )
            return APIResponse(200, {"personal_model": {"action": "delete", "status": "deleted", "ref": claim_id}})
        topic = str(payload.get("topic") or metadata.get("topic") or "").strip()
        if not topic:
            return APIResponse(409, {"error": "claim_missing_topic"})
        surface = PersonalModelUnderstandingSurface(repository=self.repository, semantic_summary_indexer=getattr(self, "semantic_summary_indexer", None))
        result = surface.update_personal_model(
            str(payload.get("episode_id") or "dashboard"),
            action=action,
            lens=str(payload.get("lens") or target.lens),
            topic=topic,
            text=str(payload.get("text") or ""),
            ref=claim_id,
            reason=reason,
            source="user_corrected" if action == "correct" else "user_said",
            personal_model_id=personal_model_id,
        )
        return APIResponse(200, {"personal_model": result})

    return APIResponse(404, {"error": "not_found"})

def _persist_proactive_ask_config(state_dir, updates: dict) -> None:
    try:
        from packages.runtime_config import (
            personal_model_question_config_from_global, global_config_path_for_state_dir,
            load_global_config, write_global_config,
        )
        config_path = global_config_path_for_state_dir(state_dir)
        config = load_global_config(config_path, state_dir=state_dir)
        question_policy = personal_model_question_config_from_global(config)
        proactive = question_policy.get("proactive_ask") if isinstance(question_policy.get("proactive_ask"), dict) else {}
        proactive.update(updates)
        question_policy["proactive_ask"] = proactive
        question_policy.pop("learning_intensity", None)
        config["personal_model_questions"] = question_policy
        write_global_config(config_path, config)
    except Exception:  # pragma: no cover
        return

def run_cron_job_now(self, job_id: str) -> dict[str, Any]:
    """Fire one cron job on demand and return its execution result.

    This is the backend for the dashboard's "Verify" button. It runs the job through
    the same CLI-runtime pipeline the scheduler uses (so ``run_count`` / ``last_run_at``
    advance exactly as if the next tick had fired), then fans the result out across
    every configured IM adapter via ``build_gateway_cron_delivery_callback`` — so
    whatever the cron agent produces lands in the user's IM as a normal cron message.
    """
    from pathlib import Path as _Path

    from apps.cli.runtime import CliRuntime
    from apps.gateway.cron_service import build_gateway_cron_delivery_callback, cron_execution_should_deliver

    state_dir = _Path(str(self.repository.database_path.parent))
    # Gateway and CLI share the same state dir and DB (`<home>/herd`) — the
    # legacy `<home>/gateway/` subdir is gone. Both surfaces read and write the
    # same `elephant.sqlite3`.
    cli_state_dir = state_dir
    gateway_state_dir = state_dir

    runtime = CliRuntime.create(state_dir=cli_state_dir)
    execution = runtime.run_cron_job_now(job_id)

    delivered = False
    delivery_error: str | None = None
    should_deliver = execution.outcome == "success" and cron_execution_should_deliver(execution)
    if should_deliver:
        try:
            callback = build_gateway_cron_delivery_callback(
                state_dir=gateway_state_dir,
                cli_state_dir=cli_state_dir,
                environ={},
            )
            if callback is not None:
                callback(execution.job, execution)
                delivered = True
        except Exception as error:
            delivery_error = f"{type(error).__name__}: {error}"

    return {
        "cron": {
            "job": _cron_job_record(execution.job),
            "run": {
                "outcome": execution.outcome,
                "summary": execution.summary,
                "delivered": delivered,
                "delivery_error": delivery_error,
                "recorded_at": execution.recorded_at.isoformat(),
            },
        }
    }

def __call__(self, environ: Mapping[str, Any], start_response: Any) -> list[bytes]:
    from .api_runtime_support import _json_bytes as encode_json

    method = str(environ.get("REQUEST_METHOD", "GET"))
    path = str(environ.get("PATH_INFO", "/"))
    payload = _read_wsgi_body(environ)
    response = self.dispatch(method, path, payload)
    start_response(
        f"{response.status_code} {'OK' if response.status_code < 400 else 'ERROR'}",
        list(response.headers),
    )
    return [encode_json(response.payload)]
