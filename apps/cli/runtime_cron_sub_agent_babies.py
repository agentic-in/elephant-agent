"""Baby elephant helpers for delegated sub-agent runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any


def resolve_baby(runtime: Any, *, backend: str, baby_id: str, role: str) -> Mapping[str, Any]:
    if backend == "local_cli":
        return _resolve_local_cli_baby(runtime, baby_id=baby_id, role=role)
    if backend == "provider":
        return _resolve_provider_baby(runtime, baby_id=baby_id, role=role)
    raise ValueError(f"unsupported baby backend: {backend}")


def compose_local_cli_baby_prompt(*, task: str, name: str | None, baby: Mapping[str, Any]) -> str:
    baby_state = baby["state"]
    runtime_record = baby["runtime"]
    role_title = str(baby.get("role_title") or "baby elephant")
    role_prompt = str(baby.get("role_prompt") or "").strip()
    identity = str(getattr(baby_state, "elephant_identity_text", "") or "").strip()
    sections = [
        "[SYSTEM: You are running as a delegated baby elephant for Elephant Agent.]",
        "Return a concise final result for Mother Elephant.",
        "Do not delegate further. Do not ask the user for clarification unless the task is impossible.",
        f"Baby elephant id: {baby_state.elephant_id}",
        f"Baby elephant name: {getattr(baby_state, 'elephant_name', '') or name or 'baby elephant'}",
        f"Role: {role_title}",
        f"Local agent provider: {runtime_record.display_name} ({runtime_record.provider_id})",
    ]
    if role_prompt:
        sections.extend(["", "Role instructions:", role_prompt])
    if identity:
        sections.extend(["", "Baby elephant identity:", identity])
    sections.extend(["", f"Delegated task:\n{task}"])
    return "\n".join(sections).strip()


def compose_provider_baby_prompt(*, task: str, name: str | None, baby: Mapping[str, Any]) -> str:
    baby_state = baby["state"]
    role_title = str(baby.get("role_title") or "baby elephant")
    role_prompt = str(baby.get("role_prompt") or "").strip()
    identity = str(getattr(baby_state, "elephant_identity_text", "") or "").strip()
    provider_id = str(baby.get("provider_id") or "").strip()
    provider_model = str(baby.get("provider_model") or "").strip()
    sections = [
        "[SYSTEM: You are running as a delegated baby elephant for Elephant Agent.]",
        "Return a concise final result for Mother Elephant.",
        "Do not delegate further. Do not ask the user for clarification unless the task is impossible.",
        f"Baby elephant id: {baby_state.elephant_id}",
        f"Baby elephant name: {getattr(baby_state, 'elephant_name', '') or name or 'baby elephant'}",
        f"Role: {role_title}",
        f"Provider runtime: {provider_id} · {provider_model}",
    ]
    if role_prompt:
        sections.extend(["", "Role instructions:", role_prompt])
    if identity:
        sections.extend(["", "Baby elephant identity:", identity])
    sections.extend(["", f"Delegated task:\n{task}"])
    return "\n".join(sections).strip()


def activate_provider_baby_profile(parent_runtime: Any, child_runtime: Any, *, prepared_child: Mapping[str, Any]) -> None:
    baby = prepared_child.get("baby")
    if not isinstance(baby, Mapping):
        raise RuntimeError("provider sub-agent is missing baby elephant binding")
    provider_id = str(baby.get("provider_id") or "").strip()
    provider_model = str(baby.get("provider_model") or "").strip()
    baby_state = baby.get("state")
    baby_id = str(getattr(baby_state, "elephant_id", "") or "provider-baby").strip()
    profile = parent_runtime.repository.select_auth_profile(provider_id)
    if provider_model and provider_model != str(profile.default_model or ""):
        profile = replace(
            profile,
            profile_id=f"{profile.profile_id}:baby:{baby_id}",
            default_model=provider_model,
            metadata={
                **dict(profile.metadata),
                "sub_agent_baby_id": baby_id,
                "sub_agent_provider_model": provider_model,
            },
        )
        child_runtime.repository.upsert_auth_profile(profile)
    child_runtime.model_provider.set_active_profile(
        provider_profile_id=profile.profile_id,
        provider_id=profile.provider_id,
    )


def _resolve_local_cli_baby(runtime: Any, *, baby_id: str, role: str) -> Mapping[str, Any]:
    target_baby_id = str(baby_id or "").strip()
    target_role = str(role or "").strip().casefold()
    candidates = []
    for state in runtime.repository.list_states(status="active"):
        metadata = dict(getattr(state, "metadata", {}) or {})
        if str(metadata.get("herd_kind") or "").strip() != "baby":
            continue
        if str(metadata.get("enabled") or "").strip().lower() != "true":
            continue
        runtime_id = str(metadata.get("runtime_id") or "").strip()
        if not runtime_id:
            continue
        if target_baby_id and target_baby_id not in {state.elephant_id, state.state_id}:
            continue
        if target_role:
            role_title = str(metadata.get("role_title") or state.elephant_name or "").strip().casefold()
            if target_role not in {role_title, state.elephant_id.casefold(), state.elephant_name.casefold()}:
                continue
        candidates.append(state)
    if not candidates:
        hint = target_baby_id or target_role or "enabled baby elephant"
        raise LookupError(f"no enabled local CLI baby elephant matched {hint!r}")
    if len(candidates) > 1 and not target_baby_id:
        labels = ", ".join(state.elephant_id for state in candidates[:6])
        raise LookupError(f"multiple baby elephants matched role {role!r}; pass baby_id. Matches: {labels}")
    state = candidates[0]
    metadata = dict(getattr(state, "metadata", {}) or {})
    load_runtime = getattr(runtime.repository, "load_local_agent_runtime", None)
    runtime_record = load_runtime(str(metadata.get("runtime_id") or "").strip()) if callable(load_runtime) else None
    if runtime_record is None:
        raise LookupError(f"local agent runtime is missing for baby elephant {state.elephant_id}")
    if not getattr(runtime_record, "can_execute", False):
        raise RuntimeError(f"local agent runtime is not executable: {runtime_record.runtime_id}")
    return {
        "state": state,
        "runtime": runtime_record,
        "provider_id": runtime_record.provider_id,
        "provider_model": str(getattr(runtime_record, "default_model", "") or ""),
        "role_title": str(metadata.get("role_title") or state.elephant_name or "baby elephant"),
        "role_prompt": str(metadata.get("role_prompt") or ""),
    }


def _resolve_provider_baby(runtime: Any, *, baby_id: str, role: str) -> Mapping[str, Any]:
    target_baby_id = str(baby_id or "").strip()
    target_role = str(role or "").strip().casefold()
    candidates = []
    for state in runtime.repository.list_states(status="active"):
        metadata = dict(getattr(state, "metadata", {}) or {})
        if str(metadata.get("herd_kind") or "").strip() != "baby":
            continue
        if str(metadata.get("enabled") or "").strip().lower() != "true":
            continue
        if str(metadata.get("backend") or "").strip().lower() != "provider":
            continue
        provider_id = str(metadata.get("provider_id") or "").strip()
        provider_model = str(metadata.get("provider_model") or metadata.get("runtime_model") or "").strip()
        if not provider_id or not provider_model:
            continue
        if target_baby_id and target_baby_id not in {state.elephant_id, state.state_id}:
            continue
        if target_role:
            role_title = str(metadata.get("role_title") or state.elephant_name or "").strip().casefold()
            if target_role not in {role_title, state.elephant_id.casefold(), state.elephant_name.casefold()}:
                continue
        candidates.append(state)
    if not candidates:
        hint = target_baby_id or target_role or "enabled provider baby elephant"
        raise LookupError(f"no enabled provider baby elephant matched {hint!r}")
    if len(candidates) > 1 and not target_baby_id:
        labels = ", ".join(state.elephant_id for state in candidates[:6])
        raise LookupError(f"multiple provider baby elephants matched role {role!r}; pass baby_id. Matches: {labels}")
    state = candidates[0]
    metadata = dict(getattr(state, "metadata", {}) or {})
    provider_id = str(metadata.get("provider_id") or "").strip()
    provider_model = str(metadata.get("provider_model") or metadata.get("runtime_model") or "").strip()
    try:
        runtime.repository.select_auth_profile(provider_id)
    except LookupError as exc:
        raise RuntimeError(f"provider profile is not configured for baby elephant {state.elephant_id}: {provider_id}") from exc
    return {
        "state": state,
        "provider_id": provider_id,
        "provider_model": provider_model,
        "role_title": str(metadata.get("role_title") or state.elephant_name or "baby elephant"),
        "role_prompt": str(metadata.get("role_prompt") or ""),
    }
