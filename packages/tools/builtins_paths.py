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
                            "delete_path",
                            "create_baby",
                            "create_step",
                            "update_step",
                            "move_step",
                            "delete_step",
                            "create_run",
                            "update_run",
                            "retry_run",
                            "write_comment",
                            "write_summary",
                            "check_understanding",
                        ],
                    },
                    "path_id": {"type": "string"},
                    "path_step_id": {"type": "string"},
                    "run_id": {"type": "string"},
                    "comment_id": {"type": "string"},
                    "parent_comment_id": {"type": "string"},
                    "summary_id": {"type": "string"},
                    "title": {"type": "string"},
                    "display_name": {"type": "string"},
                    "elephant_id": {"type": "string"},
                    "elephant_identity_text": {"type": "string"},
                    "identity_text": {"type": "string"},
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
                            "queued",
                            "dispatched",
                            "running",
                            "failed",
                            "cancelled",
                        ],
                    },
                    "priority": {
                        "type": "string",
                        "description": "Optional priority label for ordering Paths, such as normal, high, or low.",
                    },
                    "review_mode": {
                        "type": "string",
                        "enum": ["ask_first", "trusted"],
                        "default": "trusted",
                        "description": "Use trusted unless a compatibility caller explicitly needs ask_first.",
                    },
                    "owner_elephant_id": {
                        "type": "string",
                        "description": "Mother or coordinating elephant id that owns the durable Path.",
                    },
                    "parent_elephant_id": {
                        "type": "string",
                        "description": "Mother elephant id that owns a created baby elephant.",
                    },
                    "role_title": {
                        "type": "string",
                        "description": "Specialist role title when creating or resolving a baby elephant.",
                    },
                    "role_prompt": {
                        "type": "string",
                        "description": "Operating instruction for a baby elephant role.",
                    },
                    "provider_id": {
                        "type": "string",
                        "description": "Provider id for a provider-backed baby elephant.",
                    },
                    "provider_model": {
                        "type": "string",
                        "description": "Provider model id for a provider-backed baby elephant.",
                    },
                    "engine_id": {
                        "type": "string",
                        "description": "Runtime engine id Mother should bind to the created baby, such as codex, gemini, or a provider engine.",
                    },
                    "model_id": {
                        "type": "string",
                        "description": "Alias for provider_model when creating a provider-backed baby elephant.",
                    },
                    "tool_ids": {
                        "type": ["array", "string"],
                        "items": {"type": "string"},
                        "description": "Allowed tool ids for the created baby elephant. Prefer a compact explicit list over broad access.",
                    },
                    "skill_ids": {
                        "type": ["array", "string"],
                        "items": {"type": "string"},
                        "description": "Assigned skill ids or names for the created baby elephant.",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "Alias for role_prompt; stable role instruction injected into this baby's runtime prefix.",
                    },
                    "enabled": {
                        "type": ["boolean", "string"],
                        "description": "Whether a created baby elephant should be dispatchable.",
                    },
                    "max_concurrency": {
                        "type": ["integer", "string"],
                        "minimum": 1,
                        "description": "Maximum concurrent assigned runs for a created baby elephant.",
                    },
                    "backend": {
                        "type": "string",
                        "enum": ["provider", "local_cli", "native"],
                        "description": "Execution backend for a created baby elephant: provider for hosted model calls, local_cli for discovered local runtimes, native for Mother-owned/default execution.",
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
                    "attempt": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Run attempt number for a Flow step execution.",
                    },
                    "max_attempts": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Retry budget for this Flow step execution.",
                    },
                    "runtime_id": {
                        "type": "string",
                        "description": "Runtime or local computer handling a created baby elephant or Flow step run.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Execution session id for the baby elephant run.",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Workspace directory used by the run when relevant.",
                    },
                    "progress_stage": {
                        "type": "string",
                        "description": "Short machine-readable stage such as queued, planning, running, summary, or retrying.",
                    },
                    "progress_detail": {
                        "type": "string",
                        "description": "Human-readable progress detail for the current run.",
                    },
                    "progress_current": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Completed progress units when a run reports measurable progress.",
                    },
                    "progress_total": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Total progress units when a run reports measurable progress.",
                    },
                    "failure_reason": {
                        "type": "string",
                        "description": "Short reason recorded when a run fails or is cancelled.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for retry_run.",
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
                    "what_done": {
                        "type": "string",
                        "description": "Concise model-compressed summary of the core result, written for human learning.",
                    },
                    "why_it_matters": {"type": "string"},
                    "how_it_was_done": {"type": "string"},
                    "knowledge": {"type": "string"},
                    "human_takeaway": {
                        "type": "string",
                        "description": "Shortest checkable takeaway the user should absorb from this Flow step.",
                    },
                    "body": {
                        "type": "string",
                        "description": "User-facing Path step comment or baby elephant result text.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Alias for body when writing a Path step comment.",
                    },
                    "author_kind": {
                        "type": "string",
                        "enum": ["user", "elephant", "system"],
                    },
                    "author_id": {
                        "type": "string",
                        "description": "User id or elephant id for a Path step comment.",
                    },
                    "comment_type": {
                        "type": "string",
                        "enum": ["comment", "run_output", "status", "system"],
                    },
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
