"""Skill tool definitions and handler wiring for the built-in tool catalog."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .handlers_skills import run_skill_draft, run_skill_list, run_skill_manage, run_skill_view
from .runtime import ToolAvailability, ToolDefinition, ToolSideEffectMetadata
from .surfaces import BuiltinToolDependencies


def skill_tool_definitions(*, reason: str | None) -> tuple[ToolDefinition, ...]:
    availability = _availability(reason is None, reason)
    return (
        ToolDefinition(
            tool_id="tool.skill.list",
            display_name="Skill List",
            version="2.0.0",
            family="skills",
            backend="skill-runtime",
            description="List available local skill packages with their names and summaries.",
            schema=_object_schema(
                properties={
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 128,
                        "description": "Maximum number of local skill entries to return.",
                    },
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="low",
                approval_class="standard",
                writes_state=False,
                reads_state=True,
                categories=("skill", "list"),
                notes="Lists bundled, installed, and authored local skill packages.",
            ),
            availability=availability,
            metadata={"kind": "built-in"},
        ),
        ToolDefinition(
            tool_id="tool.skill.view",
            display_name="Skill View",
            version="2.0.0",
            family="skills",
            backend="skill-runtime",
            description="Inspect one skill package, including its workflow guidance, scripts, and templates.",
            schema=_object_schema(
                required=("skill_id",),
                properties={
                    "skill_id": {"type": "string", "description": "Installed skill id or local hub reference to inspect."},
                    "reference": {"type": "string", "description": "Optional local hub reference if different from skill_id."},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="low",
                approval_class="standard",
                writes_state=False,
                reads_state=True,
                categories=("skill", "view"),
                notes="Loads detailed skill instructions without mutating installed state.",
            ),
            availability=availability,
            metadata={"kind": "built-in"},
        ),
        ToolDefinition(
            tool_id="tool.skill.draft",
            display_name="Skill Draft",
            version="1.0.0",
            family="skills",
            audience="model",
            backend="skill-runtime",
            description="Create a disabled pending skill draft from repeated workflow evidence. Background learning agents only; approval happens later in the Skills surface.",
            schema=_object_schema(
                required=("action", "skill_id", "display_name", "summary", "workflow_steps"),
                properties={
                    "action": {"type": "string", "enum": ["create", "update"], "description": "Whether this is a new skill draft or an update draft for an existing skill."},
                    "skill_id": {"type": "string", "description": "Lowercase authored draft skill id, using letters, numbers, hyphens, underscores, or dots."},
                    "target_skill_id": {"type": "string", "description": "Existing skill id when action=update."},
                    "display_name": {"type": "string", "description": "Human-readable skill title."},
                    "summary": {"type": "string", "description": "Trigger-oriented description used by agents to decide when to load the skill."},
                    "category": {"type": "string", "description": "Optional authored skill category. Defaults to drafts."},
                    "candidate_key": {"type": "string", "description": "Stable candidate key from the Skill Evolution Evidence packet."},
                    "inputs": {"type": "array", "items": {"type": "string"}, "description": "Stable inputs this workflow expects."},
                    "workflow_steps": {"type": "array", "items": {"type": "string"}, "description": "Repeatable procedural steps for the skill."},
                    "outputs": {"type": "array", "items": {"type": "string"}, "description": "Expected reusable outputs or artifacts."},
                    "validation": {"type": "array", "items": {"type": "string"}, "description": "Checks that prove the workflow completed correctly."},
                    "constraints": {"type": "array", "items": {"type": "string"}, "description": "Important guardrails, privacy limits, or non-goals."},
                    "positive_examples": {"type": "array", "items": {"type": "string"}, "description": "Example user requests that should trigger the skill."},
                    "negative_examples": {"type": "array", "items": {"type": "string"}, "description": "Example requests that should not trigger the skill."},
                    "evidence_summary": {"type": "string", "description": "Short non-private summary of the evidence supporting the draft."},
                    "source_episode_ids": {"type": "array", "items": {"type": "string"}, "description": "Episode IDs supporting the draft."},
                    "overlap_reviewed_skill_ids": {"type": "array", "items": {"type": "string"}, "description": "Existing skill IDs checked for overlap."},
                    "confidence": {"type": "string", "description": "Confidence from the evidence packet, e.g. 0.72."},
                    "overwrite": {"type": "boolean", "description": "Whether to overwrite an existing pending draft with the same id."},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                writes_state=True,
                reads_state=True,
                categories=("skill", "draft"),
                notes="Writes disabled pending skill packages. It cannot enable, install, delete, or apply skills.",
            ),
            availability=availability,
            metadata={"kind": "built-in", "learning_agent_only": True},
        ),
        ToolDefinition(
            tool_id="tool.skill.manage",
            display_name="Skill Manager",
            version="2.0.0",
            family="skills",
            audience="operator",
            backend="skill-runtime",
            description="Operator-only install, enable, disable, create, update, or delete local skill packages.",
            schema=_object_schema(
                required=("action",),
                properties={
                    "action": {
                        "type": "string",
                        "enum": ["install", "enable", "disable", "create", "update", "delete", "remove"],
                    },
                    "skill_id": {"type": "string", "description": "Installed skill id, local hub reference, or authored skill id."},
                    "reference": {"type": "string", "description": "Install source reference or path when action=install."},
                    "display_name": {"type": "string", "description": "Authored skill title when action=create or update."},
                    "summary": {"type": "string", "description": "One-line authored skill summary when action=create or update."},
                    "instruction_text": {"type": "string", "description": "Full SKILL.md body when action=create or update."},
                    "category": {"type": "string", "description": "Optional authored skill category bucket."},
                    "install": {"type": "boolean", "description": "Whether to install an authored skill immediately after writing it."},
                    "overwrite": {"type": "boolean", "description": "Whether action=create may overwrite an existing authored skill."},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                writes_state=True,
                reads_state=True,
                categories=("skill", "manage"),
                notes="Operator-owned mutation surface for installed or authored skill packages.",
            ),
            availability=availability,
            metadata={"kind": "built-in"},
        ),
    )


def skill_tool_handler(
    tool_id: str,
    *,
    dependencies: BuiltinToolDependencies,
):
    if tool_id == "tool.skill.list":
        return lambda invocation: run_skill_list(invocation, surface=dependencies.skill_management)
    if tool_id == "tool.skill.view":
        return lambda invocation: run_skill_view(invocation, surface=dependencies.skill_management)
    if tool_id == "tool.skill.draft":
        return lambda invocation: run_skill_draft(invocation, surface=dependencies.skill_management)
    if tool_id == "tool.skill.manage":
        return lambda invocation: run_skill_manage(invocation, surface=dependencies.skill_management)
    return None


def _availability(is_available: bool, reason: str | None) -> ToolAvailability:
    return ToolAvailability(is_available=is_available, reason=None if is_available else reason)


def _object_schema(
    *,
    properties: Mapping[str, Any],
    required: tuple[str, ...] = (),
) -> Mapping[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
    }
    if required:
        schema["required"] = list(required)
    return schema
