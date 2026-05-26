"""Skill-aware built-in tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
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


def run_skill_draft(
    invocation: ToolInvocation,
    *,
    surface: SkillManagementSurface | None,
) -> dict[str, Any]:
    if surface is None:
        raise RuntimeError("skill management is not configured for this runtime")
    if not _learning_agent_invocation(invocation, surface):
        raise PermissionError("tool.skill.draft is only available to background learning agents")
    action = str(invocation.arguments.get("action") or "").strip().lower()
    if action not in {"create", "update"}:
        raise ValueError("tool.skill.draft requires action=create or action=update")

    skill_id = _required_draft_field(invocation, "skill_id")
    display_name = _required_draft_field(invocation, "display_name")
    summary = _required_draft_field(invocation, "summary")
    workflow_steps = _string_list(invocation.arguments.get("workflow_steps"))
    if not workflow_steps:
        raise ValueError("tool.skill.draft requires at least one workflow step")

    instruction_text = _render_draft_instruction(invocation, action=action, workflow_steps=workflow_steps)
    source_episode_ids = _string_list(invocation.arguments.get("source_episode_ids"))
    overlap_skill_ids = _string_list(invocation.arguments.get("overlap_reviewed_skill_ids"))
    metadata = {
        "default_enabled": False,
        "include_in_hub": True,
        "include_in_prompt_index": True,
        "include_in_site": False,
        "include_in_overlay": True,
        "review_status": "pending",
        "draft_kind": action,
        "target_skill_id": optional_string(invocation.arguments.get("target_skill_id")) or "",
        "candidate_key": optional_string(invocation.arguments.get("candidate_key")) or "",
        "confidence": optional_string(invocation.arguments.get("confidence")) or "",
        "source_episode_ids": source_episode_ids,
        "overlap_reviewed_skill_ids": overlap_skill_ids,
        "evidence_summary": optional_string(invocation.arguments.get("evidence_summary")) or "",
    }
    result = surface.create_authored_skill(
        skill_id=skill_id,
        display_name=display_name,
        summary=summary,
        instruction_text=instruction_text,
        category=optional_string(invocation.arguments.get("category")) or "drafts",
        install=False,
        overwrite=coerce_bool(invocation.arguments.get("overwrite"), default=False),
        source_kind="elephant-authored-draft",
        metadata=metadata,
        session_id=invocation.session_id,
    )
    return dict(
        tool_summary(
            invocation,
            "\n".join([
                *_skill_install_lines(result),
                "review_status: pending",
                "default_enabled: false",
                "approval: enable this draft from the Skills surface to make it available to normal agent loops",
            ]),
            side_effects=("tool.skill.draft", "skill", "draft"),
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
    raise ValueError(
        "tool.skill.manage requires action=install|enable|disable|create|update|delete"
    )


def _learning_agent_invocation(invocation: ToolInvocation, surface: SkillManagementSurface) -> bool:
    if invocation.requester != "model":
        return False
    repository = getattr(surface, "repository", None)
    if repository is None:
        return True
    for loader_name in ("load_episode_state", "load_episode"):
        loader = getattr(repository, loader_name, None)
        if not callable(loader):
            continue
        try:
            episode = loader(invocation.session_id)
        except Exception:
            continue
        if episode is None:
            continue
        metadata = getattr(episode, "metadata", {}) or {}
        if isinstance(metadata, Mapping) and str(metadata.get("learning_agent") or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace("\n", "|").split("|") if item.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value).strip() else ()


def _render_draft_instruction(invocation: ToolInvocation, *, action: str, workflow_steps: tuple[str, ...]) -> str:
    sections: list[str] = []
    target_skill_id = optional_string(invocation.arguments.get("target_skill_id"))
    if action == "update" and target_skill_id:
        sections.extend([
            f"This is a pending update draft for `{target_skill_id}`.",
            "Use it only after a human approves or merges the update.",
            "",
        ])
    sections.extend(_markdown_section("When to use", (str(invocation.arguments.get("summary") or "").strip(),)))
    sections.extend(_markdown_section("Inputs", _string_list(invocation.arguments.get("inputs"))))
    sections.extend(_markdown_section("Workflow", workflow_steps, numbered=True))
    sections.extend(_markdown_section("Outputs", _string_list(invocation.arguments.get("outputs"))))
    sections.extend(_markdown_section("Validation", _string_list(invocation.arguments.get("validation"))))
    sections.extend(_markdown_section("Constraints", _string_list(invocation.arguments.get("constraints"))))
    sections.extend(_markdown_section("Positive examples", _string_list(invocation.arguments.get("positive_examples"))))
    sections.extend(_markdown_section("Negative examples", _string_list(invocation.arguments.get("negative_examples"))))
    evidence_summary = optional_string(invocation.arguments.get("evidence_summary"))
    if evidence_summary:
        sections.extend(["## Evidence summary", "", evidence_summary, ""])
    return "\n".join(sections).strip()


def _markdown_section(title: str, values: tuple[str, ...], *, numbered: bool = False) -> list[str]:
    cleaned = tuple(value for value in values if value)
    if not cleaned:
        return []
    lines = [f"## {title}", ""]
    for index, value in enumerate(cleaned, start=1):
        value = _strip_markdown_list_prefix(value)
        prefix = f"{index}. " if numbered else "- "
        lines.append(f"{prefix}{value}")
    lines.append("")
    return lines


def _strip_markdown_list_prefix(value: str) -> str:
    return re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", value).strip()


def _required_field(invocation: ToolInvocation, name: str) -> str:
    value = optional_string(invocation.arguments.get(name))
    if value is None:
        raise ValueError(f"tool.skill.manage requires '{name}'")
    return value


def _required_draft_field(invocation: ToolInvocation, name: str) -> str:
    value = optional_string(invocation.arguments.get(name))
    if value is None:
        raise ValueError(f"tool.skill.draft requires '{name}'")
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
