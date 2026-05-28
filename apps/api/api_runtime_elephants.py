"""Herd and elephant HTTP dispatch helpers."""

from __future__ import annotations

from dataclasses import replace
import shutil
from typing import Any, Mapping
from urllib.parse import unquote

from packages.runtime_layout import elephant_file_path
from packages.state import render_default_elephant_identity, write_elephant_identity_file

from .api_runtime_support import APIResponse, _jsonable, _optional_str, _read_json_bytes
from .api_runtime_http_dispatch_helpers import _elephant_id_from_name
from .api_runtime_herd_local_agents import (
    baby_identity_text as _baby_identity_text,
    default_baby_display_name as _default_baby_display_name,
    herd_metadata_from_payload as _herd_metadata_from_payload,
    list_persisted_local_agents as _list_persisted_local_agents,
    local_agent_payload as _local_agent_payload,
    metadata_bool_payload as _metadata_bool_payload,
    metadata_str_payload as _metadata_str_payload,
    scan_and_persist_local_agents as _scan_and_persist_local_agents,
)


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
    try:
        states = self.repository.list_states(elephant_id=target)
    except TypeError:
        states = self.repository.list_states()
    return next((state for state in states if state.elephant_id == target), None)
def _default_elephant_identity_text(*, elephant_id: str, display_name: str) -> str:
    """Seed identity text when none is supplied via the API.

    Mirrors the CLI's first-person self-introduction template so a
    companion created through the API reads the same way a CLI-created
    companion does. Internal metadata lives in an HTML comment so it stays
    out of the prompt.
    """
    charter = render_default_elephant_identity(display_name=display_name)
    return "\n".join(
        (
            f"<!-- Internal metadata (not shown to the model). id: {elephant_id}. "
            f"Edit the paragraphs below to reshape how {display_name} introduces themselves. -->",
            "",
            charter,
        )
    )
def _elephant_identity_text_from_payload(payload: Mapping[str, Any], *, elephant_id: str, display_name: str) -> str:
    return (
        _optional_str(payload.get("elephant_identity_text") or payload.get("eggIdentityText") or payload.get("text") or payload.get("content"))
        or _default_elephant_identity_text(elephant_id=elephant_id, display_name=display_name)
    )

def _write_elephant_identity_file(self, *, elephant_id: str, text: str) -> str:
    path = write_elephant_identity_file(
        elephant_file_path(elephant_id, install_root=self.config.install_root),
        text,
    )
    return str(path)
def _dispatch_elephants(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    normalized_method = method.upper()
    if normalized_method == "POST" and parts == ("discovery", "scan"):
        records = _scan_and_persist_local_agents(self)
        return APIResponse(
            200,
            _jsonable(
                {
                    "status": "ok",
                    "discovery": [_local_agent_payload(record) for record in records],
                    "local_agent_runtimes": [_local_agent_payload(record) for record in records],
                }
            ),
        )
    if normalized_method == "GET" and parts == ("discovery",):
        records = _list_persisted_local_agents(self)
        return APIResponse(
            200,
            _jsonable(
                {
                    "status": "ok",
                    "discovery": [_local_agent_payload(record) for record in records],
                    "local_agent_runtimes": [_local_agent_payload(record) for record in records],
                }
            ),
        )
    if normalized_method == "POST" and parts == ("babies",):
        payload = _read_json_bytes(body)
        runtime_id = str(payload.get("runtime_id") or payload.get("runtimeId") or "").strip()
        if not runtime_id:
            raise ValueError("runtime_id is required")
        load_runtime = getattr(self.repository, "load_local_agent_runtime", None)
        record = load_runtime(runtime_id) if callable(load_runtime) else None
        if record is None:
            raise KeyError(runtime_id)
        if not record.can_execute:
            raise ValueError(f"runtime is not executable yet: {runtime_id}")
        role_title = _metadata_str_payload(payload, "role_title", "roleTitle") or record.role_title
        role_prompt = _metadata_str_payload(payload, "role_prompt", "rolePrompt") or record.role_prompt
        display_name = str(payload.get("display_name") or payload.get("name") or "").strip()
        if not display_name:
            display_name = _default_baby_display_name(record, role_title)
        raw_elephant_id = str(payload.get("elephant_id") or payload.get("elephantId") or "").strip()
        if raw_elephant_id and _elephant_state_for_id(self, raw_elephant_id) is not None:
            raise ValueError(f"elephant already exists: {raw_elephant_id}")
        elephant_id = raw_elephant_id or _unique_elephant_id(self, display_name)
        mother = _elephant_state_for_id(self, "mother-elephant")
        personal_model_id = str(
            payload.get("personal_model_id")
            or payload.get("profile_id")
            or (mother.personal_model_id if mother is not None else self.repository.ensure_default_personal_model().personal_model_id)
        ).strip()
        enabled = _metadata_bool_payload(payload, "enabled", "isEnabled") or "false"
        metadata = _herd_metadata_from_payload(
            {
                **dict(payload),
                "herd_kind": "baby",
                "parent_elephant_id": str(payload.get("parent_elephant_id") or payload.get("parentElephantId") or "mother-elephant"),
                "runtime_id": record.runtime_id,
                "provider_id": record.provider_id,
                "provider_model": str(payload.get("provider_model") or payload.get("providerModel") or record.default_model or ""),
                "engine_id": str(payload.get("engine_id") or payload.get("engineId") or record.provider_id or ""),
                "backend": str(payload.get("backend") or payload.get("execution_backend") or payload.get("executionBackend") or "local_cli"),
                "role_title": role_title,
                "role_prompt": role_prompt,
                "enabled": enabled,
                "max_concurrency": str(payload.get("max_concurrency") or payload.get("maxConcurrency") or "1"),
            },
            current={"profile_id": personal_model_id},
        )
        identity_text = (
            _optional_str(payload.get("elephant_identity_text") or payload.get("text") or payload.get("content"))
            or _baby_identity_text(
                display_name=display_name,
                role_title=role_title,
                role_prompt=role_prompt,
                provider_name=record.display_name,
            )
        )
        state = self.repository.create_state(
            personal_model_id=personal_model_id,
            state_id=f"state:{elephant_id}",
            state_anchor=f"elephant:{elephant_id}",
            elephant_id=elephant_id,
            elephant_name=display_name,
            identity_mode="baby",
            initiative="delegated",
            working_style="local_agent",
            surface_bindings=("api", "dashboard", "local-agent"),
            elephant_identity_text=identity_text,
            summary=f"{display_name} is available as a baby elephant for {role_title}.",
            metadata=metadata,
        )
        elephant_identity_path = _write_elephant_identity_file(self, elephant_id=elephant_id, text=identity_text)
        return APIResponse(201, _jsonable({"elephant": state, "eggIdentityPath": elephant_identity_path}))
    if normalized_method == "POST" and not parts:
        payload = _read_json_bytes(body)
        metadata_payload = dict(payload)
        herd_kind = str(metadata_payload.get("herd_kind") or metadata_payload.get("herdKind") or "").strip().lower()
        if herd_kind == "baby":
            backend = str(metadata_payload.get("backend") or metadata_payload.get("execution_backend") or metadata_payload.get("executionBackend") or "").strip().lower()
            runtime_id = str(metadata_payload.get("runtime_id") or metadata_payload.get("runtimeId") or "").strip()
            provider_id = str(metadata_payload.get("provider_id") or metadata_payload.get("providerId") or "").strip()
            provider_model = str(metadata_payload.get("provider_model") or metadata_payload.get("providerModel") or metadata_payload.get("model_id") or metadata_payload.get("modelId") or "").strip()
            engine_id = str(metadata_payload.get("engine_id") or metadata_payload.get("engineId") or metadata_payload.get("engine") or "").strip()
            if not backend:
                metadata_payload["backend"] = "local_cli" if runtime_id else "provider" if provider_id or provider_model else "native"
                backend = str(metadata_payload["backend"])
            if backend == "provider" and not provider_id and engine_id:
                metadata_payload["provider_id"] = engine_id
            if backend == "provider" and not engine_id and provider_id:
                metadata_payload["engine_id"] = provider_id
        display_name = str(payload.get("elephant_name") or payload.get("display_name") or payload.get("name") or "").strip()
        if not display_name:
            raise ValueError("display_name is required")
        raw_elephant_id = str(payload.get("elephant_id") or payload.get("eggId") or "").strip()
        if raw_elephant_id and _elephant_state_for_id(self, raw_elephant_id) is not None:
            raise ValueError(f"elephant already exists: {raw_elephant_id}")
        elephant_id = raw_elephant_id or _unique_elephant_id(self, display_name)
        personal_model_id = str(
            payload.get("personal_model_id")
            or payload.get("profile_id")
            or self.repository.ensure_default_personal_model().personal_model_id
        ).strip()
        identity_text = _elephant_identity_text_from_payload(payload, elephant_id=elephant_id, display_name=display_name)
        metadata_backend = str(metadata_payload.get("backend") or "").strip().lower()
        identity_mode = _optional_str(payload.get("mode") or payload.get("identity_mode")) or ("baby" if herd_kind == "baby" else "companion")
        initiative = _optional_str(payload.get("initiative")) or ("delegated" if herd_kind == "baby" else "gentle")
        working_style = _optional_str(payload.get("personality_preset") or payload.get("working_style")) or (
            "provider_agent" if metadata_backend == "provider" else
            "local_agent" if metadata_backend == "local_cli" else
            "delegated_specialist" if herd_kind == "baby" else
            "companion"
        )
        state = self.repository.create_state(
            personal_model_id=personal_model_id,
            state_id=f"state:{elephant_id}",
            state_anchor=f"elephant:{elephant_id}",
            elephant_id=elephant_id,
            elephant_name=display_name,
            identity_mode=identity_mode,
            initiative=initiative,
            working_style=working_style,
            surface_bindings=("api", "dashboard"),
            elephant_identity_text=identity_text,
            summary=f"{display_name} is ready to continue this elephant line.",
            metadata=_herd_metadata_from_payload(metadata_payload, current={"profile_id": personal_model_id}),
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
        personality_preset = _optional_str(payload.get("personality_preset") or payload.get("working_style"))
        initiative = _optional_str(payload.get("initiative"))
        identity_mode = _optional_str(payload.get("mode") or payload.get("identity_mode"))
        updated = replace(
            state,
            elephant_name=display_name or state.elephant_name,
            identity_mode=identity_mode if identity_mode is not None else state.identity_mode or "companion",
            initiative=initiative if initiative is not None else state.initiative,
            working_style=personality_preset if personality_preset is not None else state.working_style,
            elephant_identity_text=identity_text if identity_text is not None else state.elephant_identity_text,
            summary=f"{display_name or state.elephant_name} is ready to continue this elephant line.",
            metadata=_herd_metadata_from_payload(payload, current={**dict(state.metadata), "profile_id": state.personal_model_id}),
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
