"""Prompt rendering helpers for tool-capable model runtimes."""

from __future__ import annotations

from .runtime import ToolDefinition


def build_tool_fallback_prompt(tools: tuple[ToolDefinition, ...]) -> str:
    """Render a text fallback for transports without native tool calling."""

    if not tools:
        return ""
    tool_ids = {tool.tool_id for tool in tools}
    has_personal_model_update = "tool.personal_model.update" in tool_ids
    durable_understanding_guidance = (
        "A self-introduction, durable preference, correction, boundary, relationship rule, recurring-work context, "
        "or stable personal fact changes Elephant Agent's Personal Model. If the user explicitly asks you to remember, save, note, or keep a durable personal fact, call tool.personal_model.update before replying and do not say it was remembered unless the update tool succeeded. Use tool.personal_model.update with one lens "
        "(identity, world, pulse, journey), one dot.path topic (`lens.facet.entity[.qualifier...]`), "
        "and a grounded reason before replying. Reuse a full topic for replacement; add a qualifier for snapshots, "
        "drafts, versions, or multiple instances. Use tool.personal_model.search for durable claims, "
        "tool.conversation.search for prior conversation history, and tool.personal_model.update for durable user-stated changes. For history questions, patiently map user time wording to top-level expr such as last_night, yesterday, last:3d, or an ISO interval; never run mode=discover without expr or explicit start_at/end_at, and after discover copy the returned range start_at, end_at, and timezone into mode=recall for details. "
        "Prefer claim refs for correct/forget/dispute when the target is uncertain; restore must use an exact ref from status=all search. "
        "Use updated claims naturally without narrating storage mechanics unless asked."
        if has_personal_model_update
        else
        "Durable user understanding changes need Personal Model update tooling, but it is unavailable. State the "
        "intended durable update clearly without pretending it was stored."
    )
    tool_lines = "; ".join(
        f"{tool.display_name} ({tool.tool_id}): {tool.description}"
        for tool in tools
    )
    summaries = " ".join(tool.prompt_summary() for tool in tools)
    return (
        "available-tools: governed built-ins are available through the runtime; "
        f"{tool_lines}\n"
        "tool-call-protocol: call governed built-in tools directly when the active provider supports native "
        "tool calling. Otherwise emit <tool_call><invoke name=\"tool.id\"><parameter name=\"arg\">value"
        "</parameter></invoke></tool_call>; multiple invoke blocks are allowed, structured values may be "
        "encoded as JSON inside a parameter body, and the final answer must not include raw tool markup.\n"
        "tool-usage-discipline: use tools only when they materially advance the current request. "
        "For ordinary social conversation or acknowledgements with no durable state change, do not call any tool. "
        f"{durable_understanding_guidance} "
        "Ongoing work is carried by canonical State continuity, not by a separate durable planning structure. "
        "Use tool.process.manage only after a background process was "
        "started through tool.terminal.exec background=true. For complex tasks, cross-file changes, or work that "
        "clearly spans three or more meaningful steps, prefer using tool.todo.manage early to create or update a "
        "concise todo board even when the user did not explicitly request one. Use tool.todo.manage as an "
        "in-session execution board while working; do not present it as a durable planner or runtime hierarchy.\n"
        f"tool-parameter-schemas: {summaries}"
    )
