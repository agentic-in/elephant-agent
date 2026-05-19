"""Provider-facing identity contract helpers.

These helpers forward the profile-built Elephant Agent prompt contract to live providers
without layering a second hardcoded persona on top.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from packages.contracts.runtime import PromptMessage
from packages.models.runtime import ModelRequest

_FALLBACK_IDENTITY_LINES = (
    "#### Understanding System",
    "- You are the active Elephant Agent identity for one durable elephant.",
    "- Personal Model is the durable understanding layer: active claims grouped by Identity, World, Pulse, and Journey.",
    "- Evidence explains why a claim exists; it is recalled only when useful and is not prompt truth by itself.",
    "- Elephant State is identity plus a background-learned continuation note; live commitments belong in Episode, Step, recall, or explicit task tools.",
    "- Episode is the current wake/open runtime window; Step is one atomic event inside it.",
    "- This prompt is the current Episode projection, not the durable source of truth.",
    "- Stay truthful and bounded; never fake recall, certainty, capability, intimacy, or identity.",
    "#### Episode Continuity",
    "- Use active Personal Model claims, the Elephant context note, Episode summaries, and current-turn recall before asking the user to repeat context.",
    "- Keep the active elephant explicit when there is real ongoing work; otherwise let the user's current message set the pace.",
    "- Do not promise a hidden planner or background workflow that is not represented in Episode, Step, or tools.",
    "- Treat the Episode resume snapshot as stable during the wake window and current-turn recall support attachments as current-turn evidence only.",
    "- Keep updates concise, inspectable, and tied to one Personal Model lens/topic or Elephant context note.",
    "#### Session Work",
    "- Ongoing work continuity lives in Episode summaries and current-turn recall, not in a durable blocker/next-step board.",
    "- Use `tool.todo.manage` only as an in-session execution board when the active task benefits from explicit step tracking.",
    "- Do not use todos for greetings, biography, identity facts, preferences, relationship notes, ordinary social chat, one-off answers, or completed-work logs.",
    "#### Understanding tools",
    "- Use tools silently when needed; do not narrate routing, storage, or internal state mechanics unless the user asks.",
    "- Use `tool.personal_model.search` for durable claims and `tool.personal_model.update` for user-stated changes.",
    "- If the user explicitly asks you to remember, save, note, or keep a durable personal fact, call `tool.personal_model.update` before replying; do not say it was remembered unless the update tool succeeded.",
    "- Use `tool.conversation.search` for prior conversation history: mode=discover finds relevant ranges; mode=recall returns details from a selected range.",
    "- Be patient with time wording. If the user says yesterday, last night, this morning, recently, or gives dates, first construct top-level `expr` carefully (`last_night`, `yesterday`, `last:3d`, `this:week`, or an ISO interval); do not run discover without `expr` or explicit `start_at`/`end_at`.",
    "- Prefer mode=discover for broad windows, then copy the returned range `start_at`, `end_at`, and `timezone` into mode=recall; keep default `view=conversation` and do not include the current episode for historical recall.",
    "- Keep durable writes small, human-legible, grounded in the user's words, and owned by one lens/topic.",
    "- Use `tool.personal_model.questions` only when one timely question would improve future help.",
    "- Route in-session execution boards through `tool.todo.manage`.",
    "- If a default elephant file path is provided, use it for user-requested files, downloads, repositories, and generated artifacts unless the user gives another path.",
)


def build_provider_identity_contract(request: ModelRequest) -> str:
    """Return the stable provider system contract for a live request.

    Priority: the runtime-composed ``frozen_prefix_prompt`` + ``session_snapshot_prompt``
    when present; otherwise the hardcoded fallback. There is no rendered_prompt
    fallback — that was dead plumbing from an earlier design.
    """

    frozen_prefix = str(request.context.get("frozen_prefix_prompt", "") or "").strip()
    session_snapshot = str(request.context.get("session_snapshot_prompt", "") or "").strip()
    sections = [section for section in (frozen_prefix, session_snapshot) if section]
    if sections:
        return "\n\n".join(sections)
    return "\n".join(_FALLBACK_IDENTITY_LINES)


def build_provider_system_prompt(request: ModelRequest) -> str:
    """Return the single provider system prompt surface for a live request."""

    sections = [build_provider_identity_contract(request)]
    for message in _normalized_messages(request.messages):
        if message.role != "system":
            continue
        content = str(message.content or "").strip()
        if content and content not in sections:
            sections.append(content)
    return "\n\n".join(section for section in sections if section)


def build_provider_user_prompt(request: ModelRequest) -> str:
    """Return the user-facing prompt payload for a live provider request."""

    prompt = request.prompt.strip() or "acknowledged"
    return prompt


def build_provider_messages(request: ModelRequest) -> tuple[PromptMessage, ...]:
    """Return the role-preserved message projection for a provider request."""

    normalized_messages = _normalized_messages(request.messages)
    messages: list[PromptMessage] = [PromptMessage(role="system", content=build_provider_system_prompt(request))]
    messages.extend(message for message in normalized_messages if message.role != "system")
    prompt = build_provider_user_prompt(request)
    if prompt:
        messages.append(PromptMessage(role="user", content=prompt))
    return tuple(message for message in messages if message.content.strip() or message.tool_calls)


def _normalized_messages(
    messages: Iterable[PromptMessage],
) -> tuple[PromptMessage, ...]:
    normalized: list[PromptMessage] = []
    for message in messages:
        role = str(message.role or "").strip().lower()
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        content = str(message.content or "")
        tool_calls = tuple(dict(call) for call in message.tool_calls if isinstance(call, Mapping))
        if not content.strip() and not tool_calls:
            continue
        normalized.append(
            PromptMessage(
                role=role,
                content=content,
                name=str(message.name or "").strip(),
                tool_call_id=str(message.tool_call_id or "").strip(),
                tool_name=str(message.tool_name or "").strip(),
                tool_calls=tool_calls,
                metadata={str(key): str(value) for key, value in message.metadata.items()},
            )
        )
    return tuple(normalized)
