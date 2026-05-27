"""Built-in Path management tool definition."""

from __future__ import annotations

from .runtime import ToolAvailability, ToolDefinition, ToolSideEffectMetadata


def path_tool_definitions(*, version: str, availability: ToolAvailability) -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(
            tool_id="tool.paths.manage",
            display_name="Path Manager",
            version=version,
            description=(
                "Create and maintain durable Paths: life/work growth directions, Flow steps, "
                "herd assignment, status movement, learning summaries, and human understanding checks."
            ),
            schema={
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "create_path",
                            "update_path",
                            "create_step",
                            "update_step",
                            "move_step",
                            "write_summary",
                            "check_understanding",
                        ],
                    },
                    "path_id": {"type": "string"},
                    "path_step_id": {"type": "string"},
                    "summary_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "active",
                            "paused",
                            "completed",
                            "dropped",
                            "later",
                            "next",
                            "moving",
                            "checking",
                            "done",
                            "stuck",
                        ],
                    },
                    "priority": {
                        "type": "string",
                        "description": "Optional priority label for ordering Paths, such as normal, high, or low.",
                    },
                    "review_mode": {"type": "string", "enum": ["ask_first", "trusted"]},
                    "owner_elephant_id": {
                        "type": "string",
                        "description": "Mother or coordinating elephant id that owns the durable Path.",
                    },
                    "assignee_elephant_id": {"type": "string"},
                    "creator_elephant_id": {
                        "type": "string",
                        "description": "Elephant id that created this Flow step.",
                    },
                    "order_index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Zero-based order inside a Path column.",
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "Short title for an initial Flow step.",
                                },
                                "description": {
                                    "type": "string",
                                    "description": "Plain-language context for this initial Flow step.",
                                },
                                "status": {
                                    "type": "string",
                                    "description": "Initial Flow status such as next, moving, checking, done, or stuck.",
                                },
                                "assignee_elephant_id": {
                                    "type": "string",
                                    "description": "Baby elephant id assigned to this initial Flow step.",
                                },
                                "creator_elephant_id": {
                                    "type": "string",
                                    "description": "Elephant id that created this initial Flow step.",
                                },
                            },
                        },
                    },
                    "what_done": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "how_it_was_done": {"type": "string"},
                    "knowledge": {"type": "string"},
                    "human_takeaway": {"type": "string"},
                    "checked_by": {
                        "type": "string",
                        "description": "Actor confirming the understanding check, usually user.",
                    },
                    "note": {"type": "string"},
                    "metadata": {
                        "type": "object",
                        "description": "Optional string metadata for integrations, source ids, or policy hints.",
                    },
                },
            },
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                writes_state=True,
                reads_state=True,
                categories=("paths", "flow", "learning", "herd"),
                notes="Persists durable Path and Flow state for Mother Elephant orchestration.",
            ),
            family="paths",
            audience="both",
            availability=availability,
            backend="runtime",
            metadata={"kind": "built-in"},
        ),
    )
