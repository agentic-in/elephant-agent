"""Model-visible schema descriptions for built-in tools."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .runtime import ToolDefinition

_STRING_ARRAY_SCHEMA: Mapping[str, Any] = {"type": "string"}

_PROPERTY_DESCRIPTIONS: Mapping[str, Mapping[str, str]] = {
    "tool.terminal.exec": {
        "command": "Shell command to run in a bounded subprocess.",
        "cwd": "Working directory override for this command.",
        "timeout_seconds": "Maximum foreground command runtime in seconds.",
        "background": "Start the command as a managed background process.",
        "env": "Additional environment variables for the command.",
    },
    "tool.process.manage": {
        "process_id": "Managed process id returned by a background terminal command.",
        "input": "Text to write to the managed process stdin when action=write.",
        "timeout_seconds": "Maximum time to wait for a process action.",
    },
    "tool.browser.navigate": {"url": "URL to open in the active browser session."},
    "tool.browser.snapshot": {"full": "Capture the full page snapshot instead of the compact view."},
    "tool.browser.type": {"text": "Text to type into the referenced browser element."},
    "tool.browser.scroll": {
        "direction": "Scroll direction.",
        "amount": "Scroll amount in backend-defined units.",
    },
    "tool.browser.press": {"key": "Keyboard key to press, such as Enter or Escape."},
    "tool.browser.vision": {
        "question": "Question for the vision analyzer about the current browser screenshot.",
        "prompt": "Alternate prompt for the vision analyzer.",
        "annotate": "Whether to include visual annotations when supported.",
    },
    "tool.browser.console": {
        "clear": "Clear buffered console entries after reading them.",
        "expression": "JavaScript expression to evaluate in the page context.",
    },
    "tool.clarify": {
        "question": "One concise question to ask the user. In continuity routing, use before durable activity-plan writes only when missing tracking or structure would change what gets stored.",
        "mode": "Use open for free-form input or choice for a bounded option list.",
        "choices": "Choice labels for mode=choice, as an array or newline/comma-delimited string.",
    },
    "tool.cron.manage": {
        "action": "Use create to schedule a prompt task; use list|ls to enumerate; use inspect|pause|resume|remove|delete with a known job_id.",
        "job_id": "Cron job id to inspect, pause, resume, remove, or delete.",
        "name": "Optional human-readable job name when creating a scheduled prompt task.",
        "schedule": "Schedule phrase, ISO timestamp, interval, or cron expression for the scheduled prompt task.",
        "prompt": "The task prompt to run each time the cron job fires.",
        "skills": "Optional skill ids to load as operating instructions for the scheduled prompt task.",
        "profile_id": "Optional profile scope filter for listing or creating jobs.",
        "elephant_id": "Optional elephant scope filter for listing or creating jobs.",
    },
    "tool.sub_agents": {
        "action": "Use run|start to launch one bounded sub-agent task or a small task pool.",
        "name": "Optional label for a single sub-agent.",
        "task": "Single sub-agent assignment.",
        "prompt": "Alias for task when launching a single sub-agent.",
        "tasks": "Array of bounded sub-agent assignments for a small parallel pool.",
        "tasks[].name": "Optional label for this sub-agent task.",
        "tasks[].task": "Assignment for this sub-agent task.",
        "tasks[].prompt": "Alias for task in a task-list item.",
        "tasks[].skills": "Skill ids to load for this sub-agent task.",
        "max_concurrency": "Maximum parallel sub-agent tasks to run.",
        "skills": "Skill ids to load for a single sub-agent task.",
    },
    "tool.personal_model.search": {
        "query": "Natural-language lookup over current active Personal Model claims.",
        "query_variants": "Optional translated or paraphrased alternatives for cross-language or metaphorical lookup.",
        "lens": "Optional four-lens filter: identity, world, pulse, or journey.",
        "topic": "Optional stable topic key for lookup. Must use dot.path format.",
        "status": "Claim status filter: active, retired, disputed, or all. Defaults to active.",
        "ref": "Exact claim ref lookup independent of semantic score.",
        "include_diagnostics": "Whether to return match status, no-match reason, and per-claim scoring signals.",
        "limit": "Maximum claims to return; default is 12.",
    },
    "tool.conversation.search": {
        "query": "Content query for prior conversation search.",
        "mode": "Use discover to find relevant ranges; use recall to return details. Defaults to recall. Discover requires expr or explicit start_at/end_at.",
        "expr": "Stable time expression like last_night, yesterday, last:3d, this:week, an ISO date, or an ISO interval.",
        "start_at": "Optional RFC3339 start datetime for explicit intervals.",
        "end_at": "Optional RFC3339 end datetime for explicit intervals. End is exclusive.",
        "timezone": "Optional IANA timezone such as Asia/Shanghai.",
        "bucket": "Discover bucket size: auto, hour, or day.",
        "preview": "Discover preview style: none or anchors.",
        "view": "conversation by default; debug includes internal runtime material for diagnostics only.",
        "limit": "Maximum ranges or hits to return; default is 8.",
    },
    "tool.personal_model.update": {
        "action": "Use remember, correct, forget, dispute, or restore for one claim; restore should use an exact ref from status=all search.",
        "lens": "Four-lens owner: identity, world, pulse, or journey.",
        "topic": "Stable topic key for this claim. Must use dot.path format: lens.facet.entity[.qualifier].",
        "text": "Claim text for remember/correct.",
        "ref": "Optional claim ref from tool.personal_model.search; prefer it for correct/forget/dispute when topic is uncertain.",
        "reason": "Short grounded reason, preferably in the user's words.",
        "source": "Where the update came from: user_said, user_corrected, or learned.",
        "recall_policy": "Optional. Use only when obvious: stable, current, temporary, or review.",
    },
    "tool.personal_model.questions": {
        "action": "Use list, ask, answer, dismiss, create, update, reopen, stale, delete, inspect, or bank.",
        "question_id": "Question ref for lifecycle actions.",
        "lens": "Four-lens owner: identity, world, pulse, or journey.",
        "topic": "Question topic/sub-lens.",
        "text": "Question text for create/update.",
        "answer": "User answer; answering can settle into a Personal Model claim.",
        "reason": "Why the question exists or changed.",
    },
    "tool.message.send": {
        "body": "Outbound message body.",
        "target": "Optional delivery target override.",
        "metadata": "Optional delivery metadata.",
    },
    "tool.todo.manage": {
        "item_id": "Todo item id for inspect, update, complete, reopen, remove, or delete.",
        "title": "Todo title when creating or updating an item.",
        "status": "Todo status when creating or updating an item. Use open or done.",
        "notes": "Todo notes when creating or updating an item.",
    },
    "tool.skill.manage": {
        "action": "Use install, enable, disable, create, update, delete, or remove for operator-owned skill changes.",
    },
    "tool.skill.draft": {
        "action": "Use create for a new pending skill or update for an update draft against target_skill_id.",
        "skill_id": "Lowercase draft skill id.",
        "summary": "Trigger-oriented skill description. This is the most important routing text.",
        "workflow_steps": "Repeatable procedural steps. Keep them concise and stable.",
    },
}


def enrich_builtin_tool_schema(definition: ToolDefinition) -> ToolDefinition:
    """Return a built-in definition with complete model-visible schema guidance."""

    schema = _enrich_schema(definition.tool_id, definition.schema, ())
    return definition if schema == definition.schema else replace(definition, schema=schema)


def _enrich_schema(tool_id: str, schema: Mapping[str, Any], path: tuple[str, ...]) -> Mapping[str, Any]:
    enriched = {str(key): value for key, value in schema.items()}
    properties = enriched.get("properties")
    if isinstance(properties, Mapping):
        enriched["properties"] = {
            str(name): _enrich_property(tool_id, str(name), payload, path)
            for name, payload in properties.items()
        }
    return enriched


def _enrich_property(
    tool_id: str,
    name: str,
    payload: object,
    path: tuple[str, ...],
) -> object:
    if not isinstance(payload, Mapping):
        return payload
    next_path = (*path, name)
    enriched = {str(key): value for key, value in payload.items()}
    description = _description_for(tool_id, next_path)
    if description and not str(enriched.get("description") or "").strip():
        enriched["description"] = description
    if enriched.get("type") == "array" and "items" not in enriched:
        enriched["items"] = _STRING_ARRAY_SCHEMA
    items = enriched.get("items")
    if isinstance(items, Mapping):
        enriched["items"] = _enrich_schema(tool_id, items, (*next_path, "[]"))
    one_of = enriched.get("oneOf")
    if isinstance(one_of, list | tuple):
        enriched["oneOf"] = [_enrich_branch(tool_id, branch, next_path) for branch in one_of]
    properties = enriched.get("properties")
    if isinstance(properties, Mapping):
        enriched["properties"] = {
            str(child): _enrich_property(tool_id, str(child), child_payload, next_path)
            for child, child_payload in properties.items()
        }
    return enriched


def _enrich_branch(tool_id: str, branch: object, path: tuple[str, ...]) -> object:
    if not isinstance(branch, Mapping):
        return branch
    enriched = {str(key): value for key, value in branch.items()}
    if enriched.get("type") == "array" and "items" not in enriched:
        enriched["items"] = _STRING_ARRAY_SCHEMA
    items = enriched.get("items")
    if isinstance(items, Mapping):
        enriched["items"] = _enrich_schema(tool_id, items, (*path, "[]"))
    return enriched


def _description_for(tool_id: str, path: tuple[str, ...]) -> str | None:
    return _PROPERTY_DESCRIPTIONS.get(tool_id, {}).get(_path_key(path))


def _path_key(path: tuple[str, ...]) -> str:
    return ".".join(path).replace(".[]", "[]")


__all__ = ["enrich_builtin_tool_schema"]
