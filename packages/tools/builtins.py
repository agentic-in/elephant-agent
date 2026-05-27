"""Curated built-in tool catalog and registration for Elephant Agent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .handlers_continuity import (
    run_cron_action,
    run_todo_action,
)
from .handlers_personal_model import (
    run_conversation_search,
    run_personal_model_questions,
    run_personal_model_search,
    run_personal_model_update,
)
from .handlers_diary import run_diary_list, run_diary_write
from .builtins_skills import skill_tool_definitions, skill_tool_handler
from .builtins_sub_agents import sub_agents_tool_definitions, sub_agents_tool_handler
from .handlers_code_execution import SAFE_CODE_IMPORTS, run_code_execute
from .handlers_network import (
    run_browser_action,
    run_clarify,
    run_message_send,
    run_web_extract,
    run_web_read,
    run_web_search,
)
from .handlers_filesystem import (
    run_file_patch,
    run_file_read,
    run_file_search,
    run_file_write,
    run_terminal_exec,
)
from .handlers_process import run_process_action
from .runtime import ToolAudience, ToolAvailability, ToolDefinition, ToolRuntime, ToolSideEffectMetadata
from .schema_descriptions import enrich_builtin_tool_schema
from .surfaces import BuiltinToolDependencies

_BUILTIN_VERSION = "2.0.0"
_BUILTIN_TOOL_ORDER = (
    "terminal",
    "process",
    "file",
    "web",
    "browser",
    "clarify",
    "cron",
    "personal_model",
    "learning",
    "code_execution",
    "messaging",
    "todo",
    "skills",
    "sub_agents",
    "continuity-native",
)


def register_builtin_tools(
    runtime: ToolRuntime,
    *,
    enabled_overrides: Mapping[str, bool],
    dependencies: BuiltinToolDependencies,
) -> None:
    for definition in builtin_tool_definitions(enabled_overrides, dependencies=dependencies):
        runtime.register_tool(
            definition,
            handler=_handler_for_tool(definition, runtime=runtime, dependencies=dependencies),
        )


def builtin_tool_definitions(
    enabled_overrides: Mapping[str, bool],
    *,
    dependencies: BuiltinToolDependencies | None = None,
) -> tuple[ToolDefinition, ...]:
    browser_reason = None
    if dependencies is None or dependencies.browser_backend is None:
        browser_reason = "Browser tools require a configured browser backend."
    browser_vision_reason = browser_reason
    if browser_vision_reason is None and dependencies is not None and dependencies.browser_vision_analyzer is None:
        browser_vision_reason = "Browser vision requires a configured vision analyzer."
    message_reason = None
    if dependencies is None or dependencies.message_delivery is None:
        message_reason = "Messaging tools require a configured outbound delivery target."
    cron_reason = None
    if dependencies is None or dependencies.cron_runtime is None:
        cron_reason = "Cron management is not configured on this Elephant Agent surface."
    personal_model_reason = None
    if dependencies is None or dependencies.personal_model_understanding is None:
        personal_model_reason = "Personal Model understanding is not configured on this Elephant Agent surface."
    skill_reason = None
    if dependencies is None or dependencies.skill_management is None:
        skill_reason = "Skill management is not configured on this Elephant Agent surface."
    sub_agents_reason = None
    if dependencies is None or dependencies.sub_agents_surface is None:
        sub_agents_reason = "Sub-agent execution is not configured on this Elephant Agent surface."
    diary_reason = None
    if dependencies is None or dependencies.diary_surface is None:
        diary_reason = "Diary surface is not configured on this Elephant Agent surface."

    definitions = (
        _builtin_tool(
            tool_id="tool.terminal.exec",
            display_name="Terminal Exec",
            family="terminal",
            backend="subprocess",
            description="Run one bounded terminal command in the current root.",
            schema=_object_schema(
                required=("command",),
                properties={
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
                    "background": {"type": "boolean"},
                    "env": {"type": "object"},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="high",
                approval_class="strict",
                writes_state=True,
                reads_state=True,
                categories=("terminal", "filesystem"),
                notes="Runs a command or starts a background process inside the active root or another allowed local root.",
            ),
        ),
        _builtin_tool(
            tool_id="tool.process.manage",
            display_name="Process Manager",
            family="process",
            backend="subprocess",
            description=(
                "Inspect or control background processes previously started through "
                "tool.terminal.exec with background=true. Do not use this for ordinary chat turns or "
                "foreground commands."
            ),
            schema=_object_schema(
                required=("action",),
                properties={
                    "action": {
                        "type": "string",
                        "enum": ["list", "ls", "poll", "inspect", "wait", "write", "kill"],
                        "description": "Use list|ls to enumerate managed processes; use poll/inspect for current status and buffered stdout/stderr, wait to block for completion, write for stdin, kill to stop. Use non-buffered commands (for example python -u) for interactive echo.",
                    },
                    "process_id": {"type": "string", "description": "Managed process id returned by a background tool.terminal.exec call."},
                    "input": {"type": "string", "description": "Text to write to stdin for action=write; include a newline when the process expects line input."},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120, "description": "Maximum seconds for action=wait."},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="high",
                approval_class="strict",
                writes_state=True,
                reads_state=True,
                categories=("process", "terminal"),
                notes="Operates on background processes created by tool.terminal.exec.",
            ),
        ),
        _builtin_tool(
            tool_id="tool.file.read",
            display_name="File Read",
            family="file",
            backend="filesystem",
            description="Read a text file from the active root with bounded line pagination.",
            schema=_object_schema(
                required=("path",),
                properties={
                    "path": {"type": "string", "description": "Root-relative or absolute file path to read."},
                    "offset": {"type": "integer", "minimum": 1, "description": "1-indexed first line to read."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "description": "Maximum number of lines to read."},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="low",
                approval_class="standard",
                reads_state=True,
                categories=("file", "read"),
                notes="Reads text from a file in the active root or another allowed local root.",
            ),
        ),
        _builtin_tool(
            tool_id="tool.file.write",
            display_name="File Write",
            family="file",
            backend="filesystem",
            description="Overwrite a text file in the active root, creating parent directories as needed.",
            schema=_object_schema(
                required=("path", "content"),
                properties={
                    "path": {"type": "string", "description": "Root-relative or absolute file path to write. Must stay inside an allowed root; sensitive env, credential, and VCS metadata paths are refused."},
                    "content": {"type": "string", "description": "Complete text content to write to the file."},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="high",
                approval_class="strict",
                writes_state=True,
                reads_state=True,
                categories=("file", "write"),
                notes="Writes text to a file in the active root or another allowed local root.",
            ),
        ),
        _builtin_tool(
            tool_id="tool.file.patch",
            display_name="File Patch",
            family="file",
            backend="filesystem",
            description="Patch text files with unique replace edits, V4A patches, or unified diffs.",
            schema=_object_schema(
                required=("mode",),
                properties={
                    "mode": {
                        "type": "string",
                        "enum": ["replace", "patch"],
                        "description": (
                            "Use replace for one-file exact text edits; use patch for "
                            "V4A patch text or unified diff text. Prefer V4A for "
                            "model-authored edits because it avoids hunk header "
                            "bookkeeping."
                        ),
                    },
                    "path": {"type": "string", "description": "Root-relative or absolute file path for replace mode."},
                    "old_string": {"type": "string", "description": "Exact text to locate; must be unique unless replace_all=true."},
                    "new_string": {"type": "string", "description": "Replacement text for the matched content."},
                    "replace_all": {"type": "boolean", "description": "Replace every match instead of requiring uniqueness."},
                    "patch": {
                        "type": "string",
                        "description": (
                            "Patch text. Supported formats: unified diff with "
                            "---/+++/@@ hunks, or V4A blocks: *** Begin Patch, "
                            "*** Add File:, *** Update File:, *** Delete File:, "
                            "*** End Patch. Unified diffs still need correct "
                            "context/removal lines; V4A is more robust for "
                            "model-authored edits."
                        ),
                    },
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="high",
                approval_class="strict",
                writes_state=True,
                reads_state=True,
                categories=("file", "patch"),
                notes="Applies bounded text replacements to a file in the active root or another allowed local root.",
            ),
        ),
        _builtin_tool(
            tool_id="tool.file.search",
            display_name="File Search",
            family="file",
            backend="rg",
            description="Search active-root file contents or filenames with ripgrep.",
            schema=_object_schema(
                required=(),
                properties={
                    "query": {"type": "string", "description": "Text or regex-like pattern to search for. Required for target=content; optional for target=files, where it is treated as a glob when glob is omitted."},
                    "pattern": {"type": "string", "description": "Backward-compatible alias for query. Use query for new calls."},
                    "target": {"type": "string", "enum": ["content", "files"], "description": "Search file contents or file paths."},
                    "path": {"type": "string", "description": "Optional file or directory path to search within; must be inside the active root or another configured allowed root and cannot be a sensitive credential/VCS metadata path."},
                    "glob": {"type": "string", "description": "Optional file glob filter such as '*.py'. For target=files, omit both query and glob to list files."},
                    "include": {"type": "string", "description": "Backward-compatible alias for glob. Use glob for new calls."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Maximum number of matches to return."},
                    "offset": {"type": "integer", "minimum": 0, "description": "Number of matches to skip for pagination."},
                    "context": {"type": "integer", "minimum": 0, "maximum": 5, "description": "Context lines around content matches."},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="low",
                approval_class="standard",
                reads_state=True,
                categories=("file", "search"),
                notes="Fast search across the active root or another allowed local root.",
            ),
        ),
        _builtin_tool(
            tool_id="tool.web.search",
            display_name="Web Search",
            family="web",
            backend="duckduckgo",
            description="Search the public web and summarize the most relevant results.",
            schema=_object_schema(
                required=("query",),
                properties={
                    "query": {
                        "type": "string",
                        "description": "Search query for current public-web information.",
                    },
                    "query_variants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional translated or paraphrased query variants to try when the primary query has no results.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                        "description": "Maximum number of search results to summarize.",
                    },
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                touches_network=True,
                categories=("web", "search"),
                notes="Uses lightweight public web search with direct-result fallback.",
            ),
        ),
        _builtin_tool(
            tool_id="tool.web.read",
            display_name="Web Read",
            family="web",
            backend="urllib",
            description="Read a specific public URL and extract a text-first summary.",
            schema=_object_schema(
                required=("url",),
                properties={
                    "url": {
                        "type": "string",
                        "description": "Public http(s) URL to fetch and summarize.",
                    }
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                touches_network=True,
                categories=("web", "read"),
                notes="Fetches a public page and returns readable text.",
            ),
        ),
        _builtin_tool(
            tool_id="tool.web.extract",
            display_name="Web Extract",
            family="web",
            backend="urllib",
            description="Fetch and summarize multiple public URLs for multi-source research.",
            schema=_object_schema(
                required=("urls",),
                properties={
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "One or more public http(s) URLs to fetch.",
                    },
                    "max_urls": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Optional cap on how many URLs to process from the provided list.",
                    },
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                touches_network=True,
                categories=("web", "extract"),
                notes="Fetches multiple public pages and returns compact source-by-source summaries.",
            ),
        ),
        *_browser_tool_definitions(reason=browser_reason, vision_reason=browser_vision_reason),
        _builtin_tool(
            tool_id="tool.clarify",
            display_name="Clarify",
            family="clarify",
            backend="surface-clarify",
            description="Ask the user for clarification with an open question or a bounded choice list.",
            schema=_object_schema(
                required=("question",),
                properties={
                    "question": {"type": "string"},
                    "mode": {"type": "string", "enum": ["open", "choice"]},
                    "choices": {"type": ["array", "string"]},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="low",
                approval_class="none",
                reads_state=True,
                categories=("clarify", "interaction"),
                notes="Returns a structured clarification request when the next step is ambiguous.",
            ),
        ),
        _builtin_tool(
            tool_id="tool.cron.manage",
            display_name="Cron Manager",
            family="cron",
            backend="cron-runtime",
            description="Create, inspect, pause, resume, remove/delete, and list built-in scheduled jobs.",
            schema=_object_schema(
                required=("action",),
                properties={
                    "action": {
                        "type": "string",
                        "enum": ["list", "ls", "create", "inspect", "pause", "resume", "remove", "delete"],
                        "description": "Use list|ls without job_id; use create with schedule and prompt; use inspect|pause|resume|remove|delete with job_id.",
                    },
                    "job_id": {"type": "string", "description": "Cron job id such as cron:9f0e36022b."},
                    "name": {"type": "string", "description": "Human-readable job name when action=create."},
                    "schedule": {"type": "string", "description": "Schedule when action=create. Accepted examples: ISO timestamp '2026-05-13T09:00:00+08:00', interval '1h'/'30m'/'PT1H', or standard 5-field cron '0 2 * * *'."},
                    "prompt": {"type": "string", "description": "Prompt payload for the scheduled prompt job when action=create."},
                    "skills": {
                        "oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}],
                        "description": "Skill ids to load as operating instructions when a prompt job runs.",
                    },
                    "profile_id": {"type": "string"},
                    "elephant_id": {"type": "string"},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                writes_state=True,
                reads_state=True,
                categories=("cron", "automation"),
                notes="Govern recurring jobs for the active Elephant Agent surface.",
            ),
            availability=_availability(cron_reason is None, cron_reason),
        ),
        _builtin_tool(
            tool_id="tool.personal_model.search",
            display_name="Personal Model Search",
            family="personal_model",
            backend="understanding-runtime",
            description=(
                "Search Elephant Agent's current four-lens understanding and optional evidence. "
                "Use this before answering what Elephant Agent believes about the user or before correcting a claim."
            ),
            schema=_object_schema(
                properties={
                    "query": {"type": "string", "description": "Natural-language claim lookup."},
                    "query_variants": {"type": "array", "items": {"type": "string"}, "description": "Optional translated or paraphrased query variants for cross-lingual or metaphorical lookup; at most 5 are used."},
                    "mode": {"type": "string", "enum": ["auto", "inventory"], "description": "Search mode. Use inventory to get lens→topic list with claim counts (no content). Defaults to auto."},
                    "lens": {"type": "string", "enum": ["identity", "world", "pulse", "journey"], "description": "Optional four-lens filter."},
                    "topic": {"type": "string", "description": "Optional lens-prefixed topic key: <lens>.<domain>.<entity>[.<qualifier>], e.g. knowledge.projects.aegis.status."},
                    "status": {"type": "string", "enum": ["active", "retired", "disputed", "all"], "description": "Claim status filter. Defaults to active; use retired/all to audit old corrected claims."},
                    "ref": {"type": "string", "description": "Optional exact claim ref lookup, independent of semantic score."},
                    "include_diagnostics": {"type": "boolean", "description": "Return match status, no-match reason, and per-claim scoring signals for debugging."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "Maximum claims to return."},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="low",
                approval_class="standard",
                writes_state=False,
                reads_state=True,
                categories=("personal_model", "understanding", "search"),
                notes="Reads active Personal Model claims grouped by Identity, World, Pulse, and Journey.",
            ),
            availability=_availability(personal_model_reason is None, personal_model_reason),
        ),
        _builtin_tool(
            tool_id="tool.conversation.search",
            display_name="Conversation Search",
            family="personal_model",
            backend="understanding-runtime",
            description=(
                "Discover relevant time ranges or recall prior user/assistant conversation history. "
                "Use mode=discover for broad windows, then mode=recall with the selected range. "
                "Default view only searches turn:user, turn:assistant, and episode_summary material."
            ),
            schema=_object_schema(
                properties={
                    "query": {"type": "string", "description": "Content query for prior conversation search. Leave empty only to list a narrow time window."},
                    "mode": {"type": "string", "enum": ["discover", "recall"], "description": "Use discover to find relevant ranges; use recall to return conversation details. Defaults to recall. Discover should include expr or explicit start_at/end_at and returns recall_args lines that can be copied into a recall call."},
                    "expr": {"type": "string", "description": "Stable time expression: today, yesterday, last:24h, last:3d, this:week, previous:week, last_night, yesterday_evening, this_morning, today_afternoon, today_evening, an ISO date like 2026-05-13, or an ISO interval like 2026-05-08T18:00:00+08:00/PT12H."},
                    "start_at": {"type": "string", "description": "Optional RFC3339 start datetime for explicit intervals."},
                    "end_at": {"type": "string", "description": "Optional RFC3339 end datetime for explicit intervals. End is exclusive."},
                    "timezone": {"type": "string", "description": "Optional IANA timezone such as Asia/Shanghai; defaults to runtime timezone."},
                    "bucket": {"type": "string", "enum": ["auto", "hour", "day"], "description": "Discover bucket size. Defaults to auto."},
                    "preview": {"type": "string", "enum": ["none", "anchors"], "description": "Discover preview style. Defaults to anchors."},
                    "view": {"type": "string", "enum": ["conversation", "debug"], "description": "Use conversation by default; debug includes internal source/tool material for diagnostics only."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "Maximum ranges or hits to return."},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="low",
                approval_class="standard",
                writes_state=False,
                reads_state=True,
                categories=("conversation", "history", "search"),
                notes="Reads historical conversation turns and summaries; does not mutate Personal Model claims.",
            ),
            availability=_availability(personal_model_reason is None, personal_model_reason),
        ),
        _builtin_tool(
            tool_id="tool.personal_model.update",
            display_name="Personal Model Update",
            family="personal_model",
            backend="understanding-runtime",
            description=(
                "Remember, correct, forget, or dispute one current Personal Model claim. "
                "This is the only foreground tool for changing Elephant Agent's durable understanding."
            ),
            schema=_object_schema(
                required=("action", "lens", "topic", "reason"),
                properties={
                    "action": {"type": "string", "enum": ["remember", "correct", "forget", "dispute", "restore", "delete"], "description": "How to change the claim. Use restore with ref to reactivate a retired or disputed claim; use delete with ref only for non-protected accidental/synthetic/duplicate invalid claims that should leave the visible model entirely."},
                    "lens": {"type": "string", "enum": ["identity", "world", "pulse", "journey"], "description": "Which Personal Model lens owns the claim."},
                    "topic": {"type": "string", "description": "Lens-prefixed topic key: <lens>.<facet>.<entity>[.<qualifier>]. First segment must match lens. Facets: identity={anchor,character,values,style,body}; world={people,projects,tools,places,assets,skills}; pulse={chapter,focus,mood,blockers,intent}; journey={lessons,patterns,decisions,milestones}. Examples: identity.anchor.name.preferred, world.people.zhang_san.role, pulse.chapter.work.role, journey.lessons.collaboration.scope_creep."},
                    "text": {"type": "string", "description": "Claim text. Required for action=remember or action=correct."},
                    "ref": {"type": "string", "description": "Exact claim ref from personal_model.search. Required for delete/restore; strongly preferred for correct/forget/dispute when topic is uncertain."},
                    "reason": {"type": "string", "description": "Why this update is warranted, preferably grounded in the user's words."},
                    "source": {"type": "string", "enum": ["user_said", "user_corrected", "learned"], "description": "Where the update came from."},
                    "recall_policy": {"type": "string", "enum": ["stable", "current", "temporary", "review"], "description": "Optional; use only when obvious: stable, current, temporary, or review."},
                    "metadata": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Optional governance metadata. Skill affinity facts should include skill_id, index_id, and projection_policy when known. Skill Evolution drafts are created through tool.skill.draft, not Personal Model facts."},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                writes_state=True,
                reads_state=True,
                categories=("personal_model", "understanding", "update"),
                notes="Writes active/retired/disputed four-lens claims; free-form notes are evidence, not Personal Model truth.",
            ),
            availability=_availability(personal_model_reason is None, personal_model_reason),
        ),
        _builtin_tool(
            tool_id="tool.personal_model.questions",
            display_name="Personal Model Questions",
            family="personal_model",
            backend="understanding-runtime",
            description=(
                "Manage proactive questions tied to a Personal Model lens/topic: list, ask, answer, dismiss, create, or update. "
                "Use it only when a question would improve future help, not to fill a profile mechanically."
            ),
            schema=_object_schema(
                required=("action",),
                properties={
                    "action": {"type": "string", "enum": ["list", "inspect", "bank", "create", "update", "ask", "answer", "dismiss", "reopen", "stale", "delete"], "description": "Question lifecycle action."},
                    "question_id": {"type": "string", "description": "Question ref for inspect/update/ask/answer/dismiss/delete."},
                    "status": {"type": "string", "description": "Filter for list: open, asked, answered, dismissed, stale."},
                    "lens": {"type": "string", "enum": ["identity", "world", "pulse", "journey"], "description": "Four-lens owner."},
                    "topic": {"type": "string", "description": "Question topic or sub-lens."},
                    "text": {"type": "string", "description": "Question text for create/update."},
                    "answer": {"type": "string", "description": "User's answer; answer also creates a Personal Model claim."},
                    "reason": {"type": "string", "description": "Why this question exists or changed."},
                    "priority": {"type": "number", "minimum": 0, "maximum": 1, "description": "Priority from 0.0 to 1.0 for ordering open questions."},
                    "sensitivity": {"type": "string", "enum": ["low", "medium", "high"], "description": "How sensitive the question is for the user."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "description": "Maximum question rows to return."},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="low",
                approval_class="none",
                writes_state=True,
                reads_state=True,
                categories=("personal_model", "understanding", "questions"),
                notes="Questions are bound to Identity, World, Pulse, or Journey and can settle into claims when answered.",
            ),
            availability=_availability(personal_model_reason is None, personal_model_reason),
        ),
        _builtin_tool(
            tool_id="tool.diary.write",
            display_name="Diary Write",
            family="diary",
            backend="runtime",
            description="Write or update a diary entry for a specific date. Content should be reflective markdown prose in the user's first language.",
            audience="both",
            schema=_object_schema(required=("entry_date", "content"), properties={
                "entry_date": {"type": "string", "description": "YYYY-MM-DD date for the entry."},
                "content": {"type": "string", "description": "Markdown diary content (2-4 paragraphs)."},
                "source_episode_ids": {"type": "array", "items": {"type": "string"}, "description": "Source episode IDs."},
                "metadata": {"type": "object", "description": "Optional string metadata, such as kind=onboarding_letter."},
            }),
            side_effects=ToolSideEffectMetadata(risk_class="low", approval_class="none", writes_state=True, reads_state=False, categories=("diary", "write"), notes="Upserts one entry per date."),
            availability=_availability(diary_reason is None, diary_reason),
        ),
        _builtin_tool(
            tool_id="tool.diary.list",
            display_name="Diary List",
            family="diary",
            backend="runtime",
            description="List recent diary entries. Use to check if an entry already exists for a date.",
            audience="both",
            schema=_object_schema(required=(), properties={
                "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "Max entries (default 10)."},
                "before_date": {"type": "string", "description": "Return entries before this YYYY-MM-DD date."},
            }),
            side_effects=ToolSideEffectMetadata(risk_class="none", approval_class="none", writes_state=False, reads_state=True, categories=("diary", "read"), notes="Read-only listing."),
            availability=_availability(diary_reason is None, diary_reason),
        ),
        *sub_agents_tool_definitions(reason=sub_agents_reason),
        _builtin_tool(
            tool_id="tool.code.execute",
            display_name="Code Execute",
            family="code_execution",
            backend="python-sandbox",
            description="Run a restricted Python snippet in the active root with bounded tool RPC access.",
            schema=_object_schema(
                required=("code",),
                properties={
                    "code": {
                        "type": "string",
                        "description": f"Restricted Python snippet; safe imports include {', '.join(sorted(SAFE_CODE_IMPORTS))}. Safe builtins include pow. May call tool('tool.id', {{...}}) for allowed file/web/terminal tools. Direct open(), os, sys, random, and subprocess access are blocked.",
                    },
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 30, "description": "Maximum runtime in seconds."},
                    "mode": {
                        "type": "string",
                        "enum": ["project", "strict"],
                        "description": "project runs in the active root with the active venv/conda Python; strict runs in an isolated temp directory. Both modes enforce the same safe import/builtin policy and bounded tool RPC.",
                    },
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="high",
                approval_class="strict",
                reads_state=True,
                writes_state=True,
                touches_network=True,
                categories=("code", "python", "file", "web", "terminal"),
                notes="Subprocess Python with safe stdlib imports, scrubbed ambient secrets, and separately governed nested tool RPC.",
            ),
        ),
        _builtin_tool(
            tool_id="tool.message.send",
            display_name="Message Send",
            family="messaging",
            backend="delivery",
            description="Send an outbound message to a configured delivery target.",
            schema=_object_schema(
                required=("body",),
                properties={
                    "body": {"type": "string"},
                    "target": {"type": "string"},
                    "metadata": {"type": "object"},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="high",
                approval_class="strict",
                writes_state=True,
                reads_state=True,
                touches_network=True,
                categories=("message", "delivery"),
                notes="Only available when the current surface has an outbound delivery target.",
            ),
            availability=_availability(message_reason is None, message_reason),
        ),
        _builtin_tool(
            tool_id="tool.todo.manage",
            display_name="Todo Manager",
            family="todo",
            backend="session-todo",
            description=(
                "Manage a session-scoped execution board while working the current task. "
                "Use todos for in-session execution steps, not as a durable planner."
            ),
            schema=_object_schema(
                required=("action",),
                properties={
                    "action": {
                        "type": "string",
                        "enum": ["list", "ls", "add", "create", "inspect", "update", "complete", "reopen", "remove", "delete", "clear"],
                        "description": "Use add|create|list|clear for scratchpad setup; other actions require an item_id.",
                    },
                    "item_id": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": ["open", "done"]},
                    "notes": {"type": "string"},
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                writes_state=True,
                reads_state=True,
                categories=("todo", "scratchpad"),
                notes="Tracks short-horizon execution decomposition separately from canonical state continuity.",
            ),
        ),
        *skill_tool_definitions(reason=skill_reason),
    )
    return tuple(
        enrich_builtin_tool_schema(replace(definition, enabled=enabled_overrides.get(definition.tool_id, definition.enabled)))
        for definition in definitions
    )


def render_builtin_tool_reference_markdown() -> str:
    grouped = _group_builtin_tools(_docs_builtin_tool_definitions())
    lines: list[str] = []
    for family in _BUILTIN_TOOL_ORDER:
        tools = grouped.get(family, ())
        if not tools:
            continue
        lines.append(f"### {family}")
        for tool in tools:
            note = ""
            if not tool.available and tool.availability.reason:
                note = f" ({tool.availability.reason})"
            lines.append(f"- `{tool.tool_id}`{note}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_builtin_tool_summary_markdown() -> str:
    grouped = _group_builtin_tools(_docs_builtin_tool_definitions())
    lines: list[str] = []
    for family in _BUILTIN_TOOL_ORDER:
        tools = grouped.get(family, ())
        if not tools:
            continue
        tool_ids = ", ".join(f"`{tool.tool_id}`" for tool in tools)
        lines.append(f"- `{family}`: {tool_ids}")
    return "\n".join(lines)


def _browser_tool_definitions(*, reason: str | None, vision_reason: str | None) -> tuple[ToolDefinition, ...]:
    browser_availability = _availability(reason is None, reason)
    vision_availability = _availability(vision_reason is None, vision_reason)
    return tuple(
        _builtin_tool(
            tool_id=tool_id,
            display_name=display_name,
            family="browser",
            backend="browser-bridge",
            description=description,
            schema=schema,
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                reads_state=True,
                writes_state=tool_id not in {"tool.browser.snapshot", "tool.browser.images", "tool.browser.vision", "tool.browser.console"},
                touches_network=True,
                categories=("browser", action),
                notes="Backed by the configured browser bridge when available.",
            ),
            availability=vision_availability if tool_id == "tool.browser.vision" else browser_availability,
        )
        for tool_id, display_name, action, description, schema in (
            (
                "tool.browser.navigate",
                "Browser Navigate",
                "navigate",
                "Navigate the active browser session to a URL and return a compact ref-based page snapshot.",
                _object_schema(required=("url",), properties={"url": {"type": "string"}}),
            ),
            (
                "tool.browser.snapshot",
                "Browser Snapshot",
                "snapshot",
                "Capture a text snapshot of the active browser page, including interactive element refs.",
                _object_schema(properties={"full": {"type": "boolean"}}),
            ),
            (
                "tool.browser.click",
                "Browser Click",
                "click",
                "Click an element in the active browser page by snapshot ref, with selector fallback.",
                _object_schema(
                    properties={
                        "ref": {"type": "string", "description": "Snapshot element ref such as @e3."},
                        "selector": {"type": "string", "description": "CSS selector fallback when no ref exists."},
                    }
                ),
            ),
            (
                "tool.browser.type",
                "Browser Type",
                "type",
                "Type text into a browser element by snapshot ref, with selector fallback.",
                _object_schema(
                    required=("text",),
                    properties={
                        "ref": {"type": "string", "description": "Snapshot element ref such as @e3."},
                        "selector": {"type": "string", "description": "CSS selector fallback when no ref exists."},
                        "text": {"type": "string"},
                    },
                ),
            ),
            (
                "tool.browser.scroll",
                "Browser Scroll",
                "scroll",
                "Scroll the active page.",
                _object_schema(
                    properties={
                        "direction": {"type": "string", "enum": ("up", "down")},
                        "amount": {"type": "integer"},
                    }
                ),
            ),
            (
                "tool.browser.back",
                "Browser Back",
                "back",
                "Navigate backward in the active browser history.",
                _object_schema(properties={}),
            ),
            (
                "tool.browser.press",
                "Browser Press",
                "press",
                "Press a keyboard key in the active browser page.",
                _object_schema(required=("key",), properties={"key": {"type": "string"}}),
            ),
            (
                "tool.browser.images",
                "Browser Images",
                "images",
                "List image resources and metadata from the current page.",
                _object_schema(properties={}),
            ),
            (
                "tool.browser.vision",
                "Browser Vision",
                "vision",
                "Capture a browser screenshot and analyze it when a vision analyzer is configured.",
                _object_schema(
                    properties={
                        "question": {"type": "string"},
                        "prompt": {"type": "string"},
                        "annotate": {"type": "boolean"},
                    }
                ),
            ),
            (
                "tool.browser.console",
                "Browser Console",
                "console",
                "Inspect recent console output, JavaScript errors, or evaluate a JavaScript expression.",
                _object_schema(
                    properties={
                        "clear": {"type": "boolean"},
                        "expression": {"type": "string"},
                    }
                ),
            ),
        )
    )


def _docs_builtin_tool_definitions() -> tuple[ToolDefinition, ...]:
    return builtin_tool_definitions(
        {},
        dependencies=BuiltinToolDependencies(
            cwd=Path("/tmp"),
            cron_runtime=object(),  # type: ignore[arg-type]
            personal_model_understanding=object(),  # type: ignore[arg-type]
            skill_management=object(),  # type: ignore[arg-type]
            sub_agents_surface=object(),  # type: ignore[arg-type]
            browser_backend=object(),  # type: ignore[arg-type]
        ),
    )

def _builtin_tool(
    *,
    tool_id: str,
    display_name: str,
    family: str,
    backend: str,
    description: str,
    schema: Mapping[str, Any],
    side_effects: ToolSideEffectMetadata,
    availability: ToolAvailability | None = None,
    audience: ToolAudience = "both",
) -> ToolDefinition:
    return ToolDefinition(
        tool_id=tool_id,
        display_name=display_name,
        version=_BUILTIN_VERSION,
        description=description,
        schema=schema,
        side_effects=side_effects,
        family=family,
        audience=audience,
        availability=availability or ToolAvailability(),
        backend=backend,
        metadata={"kind": "built-in"},
    )


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


def _group_builtin_tools(definitions: tuple[ToolDefinition, ...]) -> dict[str, tuple[ToolDefinition, ...]]:
    grouped: dict[str, list[ToolDefinition]] = {}
    for definition in definitions:
        grouped.setdefault(definition.family, []).append(definition)
    return {family: tuple(items) for family, items in grouped.items()}


def _handler_for_tool(
    definition: ToolDefinition,
    *,
    runtime: ToolRuntime,
    dependencies: BuiltinToolDependencies,
):
    tool_id = definition.tool_id
    if tool_id == "tool.terminal.exec":
        return lambda invocation: run_terminal_exec(invocation, dependencies=dependencies)
    if tool_id == "tool.process.manage":
        return lambda invocation: run_process_action(invocation, manager=dependencies.process_manager)
    if tool_id == "tool.file.read":
        return lambda invocation: run_file_read(
            invocation,
            cwd=dependencies.resolve_cwd(invocation.session_id),
            allowed_roots=(dependencies.cwd, *invocation.context.allowed_roots, *dependencies.additional_allowed_roots),
            file_read_optimizer=dependencies.file_read_optimizer,
        )
    if tool_id == "tool.file.write":
        return lambda invocation: run_file_write(
            invocation,
            cwd=dependencies.resolve_cwd(invocation.session_id),
            allowed_roots=(dependencies.cwd, *invocation.context.allowed_roots, *dependencies.additional_allowed_roots),
        )
    if tool_id == "tool.file.patch":
        return lambda invocation: run_file_patch(
            invocation,
            cwd=dependencies.resolve_cwd(invocation.session_id),
            allowed_roots=(dependencies.cwd, *invocation.context.allowed_roots, *dependencies.additional_allowed_roots),
        )
    if tool_id == "tool.file.search":
        return lambda invocation: run_file_search(
            invocation,
            cwd=dependencies.resolve_cwd(invocation.session_id),
            allowed_roots=(dependencies.cwd, *invocation.context.allowed_roots, *dependencies.additional_allowed_roots),
        )
    if tool_id == "tool.web.search":
        return lambda invocation: run_web_search(invocation, user_agent=dependencies.web_user_agent)
    if tool_id == "tool.web.read":
        return lambda invocation: run_web_read(invocation, user_agent=dependencies.web_user_agent)
    if tool_id == "tool.web.extract":
        return lambda invocation: run_web_extract(invocation, user_agent=dependencies.web_user_agent)
    if tool_id.startswith("tool.browser."):
        return lambda invocation: run_browser_action(invocation, backend=dependencies.browser_backend, vision_analyzer=dependencies.browser_vision_analyzer)
    if tool_id == "tool.clarify":
        return lambda invocation: run_clarify(invocation, surface=dependencies.clarify_surface)
    if tool_id == "tool.cron.manage":
        return lambda invocation: run_cron_action(invocation, runtime=dependencies.cron_runtime)
    if tool_id == "tool.personal_model.search":
        return lambda invocation: run_personal_model_search(invocation, surface=dependencies.personal_model_understanding)
    if tool_id == "tool.conversation.search":
        return lambda invocation: run_conversation_search(invocation, surface=dependencies.personal_model_understanding)
    if tool_id == "tool.personal_model.update":
        return lambda invocation: run_personal_model_update(invocation, surface=dependencies.personal_model_understanding)
    if tool_id == "tool.personal_model.questions":
        return lambda invocation: run_personal_model_questions(invocation, surface=dependencies.personal_model_understanding)
    if tool_id == "tool.code.execute":
        return lambda invocation: run_code_execute(
            invocation,
            runtime=runtime,
            allowlist=dependencies.code_tool_allowlist,
            cwd=dependencies.resolve_cwd(invocation.session_id),
        )
    skill_handler = skill_tool_handler(tool_id, dependencies=dependencies)
    if skill_handler is not None:
        return skill_handler
    sub_agents_handler = sub_agents_tool_handler(tool_id, dependencies=dependencies)
    if sub_agents_handler is not None:
        return sub_agents_handler
    if tool_id == "tool.diary.write":
        return lambda invocation: run_diary_write(invocation, surface=dependencies.diary_surface)
    if tool_id == "tool.diary.list":
        return lambda invocation: run_diary_list(invocation, surface=dependencies.diary_surface)
    if tool_id == "tool.message.send":
        return lambda invocation: run_message_send(invocation, surface=dependencies.message_delivery)
    if tool_id == "tool.todo.manage":
        return lambda invocation: run_todo_action(invocation, store=dependencies.todo_store)
    return None

__all__ = ["BuiltinToolDependencies", "builtin_tool_definitions", "register_builtin_tools", "render_builtin_tool_reference_markdown", "render_builtin_tool_summary_markdown"]
