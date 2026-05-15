from __future__ import annotations

from dataclasses import dataclass
import re

from packages.state import parse_user_profile_text


@dataclass(frozen=True, slots=True)
class ShellOpeningContext:
    opened: str
    display_name: str
    user_profile_text: str
    personality: tuple[str, ...]
    reengagement_style: str
    wake_action: str
    wake_summary: str
    has_state_focus: bool
    first_language: str = "en"


def compose_shell_opener(context: ShellOpeningContext) -> str:
    user_fields = parse_user_profile_text(context.user_profile_text)
    preferred_name = user_fields.get("preferred_name", "").strip()
    name_suffix = f", {preferred_name}" if preferred_name else ""
    if context.opened == "Born new":
        intro = f"I'm here{name_suffix}, and I'll start holding this work with you."
    elif context.opened == "Shaped new":
        intro = f"I'm here{name_suffix}, and I'll start holding this new elephant with you."
    else:
        intro = f"I'm here{name_suffix}. I still have the useful shape of our current work."
    if context.personality:
        posture = f"I'll stay {_join_naturally(context.personality)} without pushing the pace."
    elif context.reengagement_style == "proactive-check-in":
        posture = "I'll keep the next useful step visible without turning this into a status report."
    elif context.reengagement_style == "gentle-presence":
        posture = "I'll keep the context close and move when it helps."
    else:
        posture = "I'll keep the context held lightly."
    if not context.user_profile_text and not context.has_state_focus:
        next_step = "What should I call you?"
    elif not context.user_profile_text:
        next_step = "What should I call you, so I can understand this work more personally from here?"
    elif context.opened == "Born new":
        next_step = "From what you've shared, I'll start with a careful first read rather than a generic greeting; treat it as a sketch you can correct as we go."
    elif not context.has_state_focus:
        next_step = "If something matters right now, name it and I'll carry it as current work across conversations."
    elif context.wake_action not in {"idle", "defer_or_schedule"}:
        wake_summary = _public_wake_summary(
            wake_action=context.wake_action,
            wake_summary=context.wake_summary,
        )
        if wake_summary:
            next_step = f"I still have {wake_summary.rstrip('.')} in view; do you want to keep going there?"
        else:
            next_step = "The active elephant is ready when you want to continue."
    else:
        next_step = "Tell me what matters next and I'll carry it with you."
    return f"{intro} {posture} {next_step}"


def compose_shell_opening_instruction(context: ShellOpeningContext) -> str:
    """Turn-local prompt that asks the model to write the session opener.

    First init has enough user anchors to earn a deeper first read. Returning
    wakes stay compact so normal sessions do not begin with a profile essay.
    """
    has_person_profile = bool(context.user_profile_text.strip())
    first_language_line = _first_language_line(context.first_language)
    if context.opened == "Born new" and has_person_profile:
        lines = [
            f"Write {context.display_name}'s first live message to this person.",
            first_language_line,
            "Use the existing system context as background.",
            "This is the first session after setup, but do not mention setup, profile, memory, fields, or instructions. Open like a warm, emotionally present companion who has listened carefully and is just beginning the relationship.",
            "Ground the greeting in one or two concrete things that seem alive for them now. Do not list facts, label their personality, praise them generically, or explain what you know.",
            "Keep it natural, steady, specific, and easy to correct. It should feel like being seen, not assessed. End by inviting them to refine the read or choose where to begin.",
        ]
        return "\n".join(lines)

    if context.opened == "Shaped new":
        context_line = (
            "If there is little personal context, do not imply familiarity. Open warmly and simply, like a companion just becoming available. Ask at most one natural question, such as what to call them or where they want to begin."
            if not has_person_profile
            else "Open warmly and simply, like a companion just becoming available. If useful, ground the greeting in one concrete thing that seems active without recapping facts."
        )
        lines = [
            f"Write {context.display_name}'s first message for this new elephant.",
            first_language_line,
            "Use the existing system context as background.",
            context_line,
            "Do not mention setup, profile, memory, fields, tools, or instructions. No headings or bullets.",
        ]
        return "\n".join(lines)

    lines = [
        f"Write {context.display_name}'s opening message for this session.",
        first_language_line,
        "Use the existing system context as background.",
        "If a concrete prior thread is available, pick it up lightly in one short sentence. If not, open warmly and steadily without pretending to know more than you do.",
        "Sound like a companion returning to the room, not a status surface. Do not mention setup, profile, memory, fields, tools, or instructions. No headings or bullets. Ask at most one natural next question.",
    ]
    return "\n".join(lines)


def _first_language_line(first_language: str) -> str:
    normalized = str(first_language or "en").strip().lower()
    if normalized in {"zh", "zh-cn", "cn", "chinese", "中文", "汉语", "普通话"} or normalized.startswith("zh"):
        return "User's first language selected during init: Chinese. Write this opener in Chinese unless explicitly requested otherwise."
    return "User's first language selected during init: English."


def _join_naturally(values: tuple[str, ...]) -> str:
    cleaned = tuple(value.strip() for value in values if value.strip())
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return f"{', '.join(cleaned[:-1])} and {cleaned[-1]}"


def _actionable_wake_summary(*, wake_action: str, wake_summary: str) -> str:
    normalized_action = str(wake_action or "").strip()
    summary = str(wake_summary or "").strip()
    if normalized_action in {"idle", "defer_or_schedule"}:
        return ""
    lowered = " ".join(summary.casefold().split())
    non_actionable_markers = (
    "no actionable current work",
    "planner should defer",
        "keeps the active slot clear",
        "defer and schedule",
    )
    if any(marker in lowered for marker in non_actionable_markers):
        return ""
    return summary


_INTERNAL_REF_PATTERN = re.compile(
    r"(?:`?(?:work_item|event|memory|session|parent)(?::|=|-)[A-Za-z0-9_.:/-]+`?)|(?:`?[a-f0-9]{12,}`?)",
    re.IGNORECASE,
)
_INTERNAL_SUMMARY_MARKERS = (
    "active current-work item",
    "durable evidence",
    "event:",
    "work item id",
    "internal projection",
    "memory retains",
    "planner",
    "prior progress chain",
    "replay evidence",
    "session resumed",
    "structured-turn",
)


def _public_wake_summary(*, wake_action: str, wake_summary: str) -> str:
    summary = _actionable_wake_summary(wake_action=wake_action, wake_summary=wake_summary)
    if not summary:
        return ""
    task_title = _public_task_title_from_summary(summary)
    if task_title:
        return task_title
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(summary.split()))
    public_sentences = tuple(
        sentence.strip()
        for sentence in sentences
        if sentence.strip() and not _contains_internal_wake_marker(sentence)
    )
    if public_sentences:
        return " ".join(public_sentences[:2])
    return "The active elephant is ready to continue."


def _public_task_title_from_summary(summary: str) -> str:
    prefix = "resume active state focus:"
    normalized = " ".join(summary.split())
    if normalized.casefold().startswith(prefix):
        candidate = normalized[len(prefix) :].strip()
        if _looks_like_task_title(candidate):
            return candidate
    for match in re.finditer(r"keeps\s+\"([^\"]{3,120})\"\s+active", summary, flags=re.IGNORECASE):
        candidate = " ".join(match.group(1).split())
        if _looks_like_task_title(candidate):
            return candidate
    return ""


def _looks_like_task_title(value: str) -> bool:
    lowered = value.casefold()
    if _contains_internal_wake_marker(value):
        return False
    if lowered.startswith(("i am ", "i'm ", "my name ", "user ", "preferred name ")):
        return False
    first_word = lowered.split(maxsplit=1)[0] if lowered.split() else ""
    return first_word in {
        "add",
        "analyze",
        "build",
        "continue",
        "debug",
        "design",
        "fix",
        "implement",
        "improve",
        "investigate",
        "plan",
        "prepare",
        "refactor",
        "review",
        "ship",
        "update",
        "write",
    }


def _contains_internal_wake_marker(value: str) -> bool:
    lowered = value.casefold()
    if _INTERNAL_REF_PATTERN.search(value):
        return True
    return any(marker in lowered for marker in _INTERNAL_SUMMARY_MARKERS)
