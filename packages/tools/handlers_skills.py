"""Skill-aware built-in tool handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from packages.skills import skill_provenance_fields

from .handler_support import coerce_bool, coerce_int, optional_string, tool_summary
from .runtime import ToolInvocation
from .surfaces import SkillManagementSurface


def run_skill_list(
    invocation: ToolInvocation,
    *,
    surface: SkillManagementSurface | None,
) -> dict[str, Any]:
    if surface is None:
        raise RuntimeError("skill management is not configured for this runtime")
    limit = max(1, min(coerce_int(invocation.arguments.get("limit"), default=24), 128))
    entries = _model_skill_list_entries(surface.list_skill_hub(limit=None), limit=limit)
    lines = [
        f"{entry.skill_id} | {entry.display_name} | source={entry.source_id} | reference={entry.reference} | {entry.summary}"
        for entry in entries
    ] or ["<empty>"]
    return dict(
        tool_summary(
            invocation,
            "\n".join(lines),
            side_effects=("skill", "list"),
        )
    )


def _model_skill_list_entries(entries: tuple[Any, ...], *, limit: int) -> tuple[Any, ...]:
    """Keep user-configured shelves visible even when the built-in catalog is large."""
    ranked = sorted(
        entries,
        key=lambda entry: (
            _skill_source_priority(str(getattr(entry, "source_id", ""))),
            str(getattr(entry, "display_name", "")).lower(),
            str(getattr(entry, "skill_id", "")),
        ),
    )
    return tuple(ranked[:limit])


def _skill_source_priority(source_id: str) -> int:
    if source_id in {"elephant-installed", "elephant-authored"}:
        return 0
    if source_id != "builtin":
        return 1
    return 2


def run_skill_view(
    invocation: ToolInvocation,
    *,
    surface: SkillManagementSurface | None,
) -> dict[str, Any]:
    if surface is None:
        raise RuntimeError("skill management is not configured for this runtime")
    reference = (
        optional_string(invocation.arguments.get("skill_id"))
        or optional_string(invocation.arguments.get("reference"))
        or optional_string(invocation.arguments.get("name"))
    )
    if reference is None:
        raise ValueError("tool.skill.view requires 'skill_id' or 'reference'")
    skill = surface.inspect_skill(reference, session_id=invocation.session_id)
    lines = [
        f"skill_id: {skill.skill_id}",
        f"display_name: {skill.display_name}",
        f"enabled: {skill.enabled}",
        f"version: {skill.version}",
        f"summary: {skill.summary}",
        f"provenance: {skill.provenance or 'built-in'}",
    ]
    installed = skill.metadata.get("installed")
    if isinstance(installed, bool):
        lines.append(f"installed: {installed}")
    lines.extend(_skill_provenance_lines(skill.metadata))
    slash_command = optional_string(skill.metadata.get("slash_command"))
    if slash_command is not None:
        lines.append(f"slash_command: /{slash_command}")
    if skill.instruction_text.strip():
        lines.extend(["", skill.instruction_text.strip()])
    return dict(
        tool_summary(
            invocation,
            "\n".join(lines),
            side_effects=("skill", "view"),
        )
    )


def run_skill_manage(
    invocation: ToolInvocation,
    *,
    surface: SkillManagementSurface | None,
) -> dict[str, Any]:
    if surface is None:
        raise RuntimeError("skill management is not configured for this runtime")
    action = str(invocation.arguments.get("action") or "").strip().lower()
    session_id = invocation.session_id
    if action in {"enable", "disable"}:
        skill_id = _required_skill_reference(invocation)
        updated = surface.set_skill_enabled(skill_id, action == "enable", session_id=session_id)
        return dict(
            tool_summary(
                invocation,
                f"skill_id: {updated.skill_id}\nenabled: {updated.enabled}",
                side_effects=("skill", action),
            )
        )
    if action == "install":
        reference = _required_skill_reference(invocation)
        result = surface.install_skill_source(
            reference,
            session_id=session_id,
            requester=invocation.requester,
        )
        return dict(
            tool_summary(
                invocation,
                "\n".join(_skill_install_lines(result)),
                side_effects=("skill", "install"),
            )
        )
    if action == "create":
        result = surface.create_authored_skill(
            skill_id=_required_field(invocation, "skill_id"),
            display_name=_required_field(invocation, "display_name"),
            summary=_required_field(invocation, "summary"),
            instruction_text=_required_field(invocation, "instruction_text"),
            category=optional_string(invocation.arguments.get("category")),
            install=coerce_bool(invocation.arguments.get("install"), default=True),
            overwrite=coerce_bool(invocation.arguments.get("overwrite"), default=False),
            session_id=session_id,
        )
        return dict(
            tool_summary(
                invocation,
                "\n".join(_skill_install_lines(result)),
                side_effects=("skill", "create"),
            )
        )
    if action == "update":
        skill_id = _required_skill_reference(invocation)
        result = surface.update_authored_skill(
            skill_id,
            display_name=optional_string(invocation.arguments.get("display_name")),
            summary=optional_string(invocation.arguments.get("summary")),
            instruction_text=optional_string(invocation.arguments.get("instruction_text")),
            category=optional_string(invocation.arguments.get("category")),
            session_id=session_id,
        )
        return dict(
            tool_summary(
                invocation,
                "\n".join(_skill_install_lines(result)),
                side_effects=("skill", "update"),
            )
        )
    if action in {"delete", "remove"}:
        skill_id = _required_skill_reference(invocation)
        removed_skill_id, removed_path = surface.delete_skill_source(skill_id, session_id=session_id)
        return dict(
            tool_summary(
                invocation,
                f"skill_id: {removed_skill_id}\nremoved_path: {removed_path}",
                side_effects=("skill", "delete"),
            )
        )
    raise ValueError("tool.skill.manage requires action=install|enable|disable|create|update|delete")


def _required_field(invocation: ToolInvocation, name: str) -> str:
    value = optional_string(invocation.arguments.get(name))
    if value is None:
        raise ValueError(f"tool.skill.manage requires '{name}'")
    return value


def _required_skill_reference(invocation: ToolInvocation) -> str:
    value = (
        optional_string(invocation.arguments.get("skill_id"))
        or optional_string(invocation.arguments.get("reference"))
        or optional_string(invocation.arguments.get("name"))
    )
    if value is None:
        raise ValueError("tool.skill.manage requires 'skill_id' or 'reference'")
    if value.startswith("/") and Path(value).exists():
        return value
    return value


def _skill_provenance_lines(metadata: Any) -> list[str]:
    return [f"{label}: {value}" for label, value in skill_provenance_fields(metadata or {})]


def _skill_install_lines(result: Any) -> list[str]:
    lines = [
        f"source_path: {result.source_path}",
        f"skill_ids: {', '.join(result.skill_ids) or '<empty>'}",
        f"status: {result.status}",
    ]
    detail = str(getattr(result, "detail", "") or "").strip()
    if detail:
        lines.append(f"detail: {detail}")
    lines.extend(_skill_provenance_lines(getattr(result, "metadata", {})))
    return lines
