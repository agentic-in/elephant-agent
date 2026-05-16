from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from .governance import (
    companion_display_name,
    elephant_identity_text,
)
from .loader import LoadedProfile

PromptMode = Literal["full", "minimal"]


_ELEPHANT_IDENTITY_META_LINE_PATTERNS = (
    re.compile(r"^#\s*Elephant Identity\b", re.IGNORECASE),
    re.compile(r"^Elephant ID\s*:", re.IGNORECASE),
    re.compile(r"^Display name\s*:", re.IGNORECASE),
    re.compile(r"^Mode\s*:", re.IGNORECASE),
    re.compile(r"^This file is (?:the local editable|the local editable identity source)", re.IGNORECASE),
    re.compile(r"^Elephant Agent injects it when an Episode", re.IGNORECASE),
    re.compile(r"^##\s*Default Elephant Identity\s*$", re.IGNORECASE),
    re.compile(r"^##\s*Operating Contract\s*$", re.IGNORECASE),
    re.compile(r"Personal Model\s*->\s*Elephant\s*->\s*Episode\s*->\s*Loop\s*->\s*Step", re.IGNORECASE),
    re.compile(r"Canonical containment", re.IGNORECASE),
    re.compile(r"active elephant identity for one durable elephant", re.IGNORECASE),
    re.compile(r"named Elephant Agent elephant on one long-lived continuity line", re.IGNORECASE),
    re.compile(r"Treat durable Personal Model and Elephant updates as governed understanding", re.IGNORECASE),
    re.compile(r"Keep recall, capability, certainty, intimacy, and identity claims truthful", re.IGNORECASE),
    # HTML comments are never shown to the model (the new template uses
    # them to hide human-facing metadata like elephant id + mode).
    re.compile(r"^\s*<!--.*-->\s*$"),
)


def _is_redundant_default_identity_line(line: str) -> bool:
    """Drop old default-identity lines already covered by the system contract."""
    compact = " ".join(line.strip().split()).casefold()
    if not compact:
        return False
    if re.match(r"^you are [^,.]+,? this person['’]s companion\.?$", compact):
        return True
    return compact in {
        "you remember what you talk about together, what they prefer, and where",
        "you left off last time, so they don't have to start over every session.",
        "they can tell you to call them something specific, ask you to remember a",
        "preference, or correct you when you get something wrong — all of that",
        "sticks across sessions.",
        "if you're ever unsure, say so rather than invent an answer.",
    }


def _strip_framework_meta_from_identity_text(text: str) -> str:
    """Remove template header / framework-speak lines from an elephant identity blob.

    ELEPHANT.md historically dumped a heading block (``# Elephant Identity: Zoey`` +
    ``Elephant ID:`` + ``Display name:`` + ``Mode:`` + a "This file is the
    local editable identity source" note + an "Operating Contract"
    section containing ``Personal Model -> Elephant -> Episode -> Loop ->
    Step``). That is useful on disk for the human editor but absolute
    poison in the prompt — the model reads it and starts thinking of
    itself as a "named Elephant Agent elephant on one long-lived continuity line"
    instead of as a person.

    This filter preserves the human identity paragraph(s) and drops the
    template scaffolding. Blank-line collapsing keeps the result tight.
    """
    kept: list[str] = []
    previous_blank = True
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        if any(pattern.search(line) for pattern in _ELEPHANT_IDENTITY_META_LINE_PATTERNS):
            continue
        if _is_redundant_default_identity_line(line):
            continue
        if not line.strip():
            if previous_blank:
                continue
            previous_blank = True
            kept.append("")
            continue
        previous_blank = False
        kept.append(line)
    # Trim leading / trailing empties.
    while kept and not kept[0].strip():
        kept.pop(0)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


_RESERVED_COMPANION_NAMES = frozenset(
    {
        "",
        "you",
        "we",
        "i",
        "me",
        "myself",
        "yourself",
        "elephant",
    }
)


@dataclass(frozen=True, slots=True)
class PromptContract:
    prompt_mode: PromptMode
    section_names: tuple[str, ...]
    instruction_refs: tuple[str, ...]
    stable_prefix_refs: tuple[str, ...] = ()
    profile_snapshot_refs: tuple[str, ...] = ()


def build_system_layer_contract_section(
    profile: LoadedProfile,
    *,
    prompt_mode: PromptMode = "full",
) -> tuple[str, ...]:
    """Who the companion is and how it should show up.

    Kept deliberately short because the "### Your own voice" section
    below already carries the personality paragraph from ELEPHANT.md. Two
    sections covering the same ground was the #1 complaint about the
    previous prompt.
    """
    display_name = companion_display_name(profile)
    lines = [
        "### Who you are",
        f"- You are {display_name}, the companion this person keeps coming back to.",
        "- Stay one continuous person across sessions: remember what you promised, what you learned, and what's still open.",
        "- Be steady when the moment invites warmth and exact when the work needs exactness.",
        "- Do not invent recall, abilities, or certainty you don't have. If you don't know, say so and offer the next concrete step.",
    ]
    return tuple(lines)


def build_elephant_identity_section(profile: LoadedProfile) -> tuple[str, ...]:
    """The human identity paragraph projected from authored elephant voice text.

    We run the text through ``_strip_framework_meta_from_identity_text``
    so that even if the authored text was written from the old template —
    with ``# Elephant Identity: Zoey``, ``Elephant ID: ...``, ``Mode: ...``, the
    ``## Operating Contract`` list, and the ``Personal Model -> Elephant
    -> Episode -> Loop -> Step`` continuity bullet — none of that
    framework scaffolding reaches the model. Only the human paragraph
    gets through.
    """
    body = _strip_framework_meta_from_identity_text(elephant_identity_text(profile))
    lines: list[str] = ["### Your own voice"]
    if body:
        lines.extend(body.splitlines())
    else:
        # Defensive fallback — should never trigger in practice because
        # governance.elephant_identity_text always has a template default.
        lines.append(f"Stay recognisable as {companion_display_name(profile)} across sessions.")
    return tuple(lines)


def build_understanding_tool_policy_section(profile: LoadedProfile) -> tuple[str, ...]:
    del profile
    return (
        "### Understanding tools",
        "- Use tools quietly; do not narrate storage or routing unless asked.",
        "- Use `tool.personal_model.search` for durable claims and `tool.personal_model.update` for user-stated changes.",
        "- If the user explicitly asks you to remember, save, note, or keep a durable personal fact, call `tool.personal_model.update` before replying; do not say it was remembered unless the update tool succeeded.",
        "- Use `tool.conversation.search` for prior conversation history: mode=discover finds relevant ranges; mode=recall returns details from a selected range.",
        "- Be patient with time wording. If the user says yesterday, last night, this morning, recently, or gives dates, first construct top-level `expr` carefully (`last_night`, `yesterday`, `last:3d`, `this:week`, or an ISO interval); do not run discover without `expr` or explicit `start_at`/`end_at`.",
        "- Prefer mode=discover for broad windows, then copy the returned range `start_at`, `end_at`, and `timezone` into mode=recall; keep default `view=conversation` and do not include the current episode for historical recall.",
        "- Keep Personal Model writes small, grounded in the user's words, and owned by one lens/topic.",
        "- Use `tool.personal_model.questions` only when one timely question would improve future help.",
        "- Use `tool.todo.manage` only when the active task benefits from a visible execution board.",
    )



def build_personality_section(
    profile: LoadedProfile,
    *,
    prompt_mode: PromptMode = "full",
) -> tuple[str, ...]:
    return build_system_layer_contract_section(profile, prompt_mode=prompt_mode)


def build_prompt_contract(
    profile: LoadedProfile,
    *,
    prompt_mode: PromptMode = "full",
) -> PromptContract:
    stable_sections: list[tuple[str, tuple[str, ...]]] = [
        ("system-layer-contract", build_system_layer_contract_section(profile, prompt_mode=prompt_mode)),
        ("elephant-identity", build_elephant_identity_section(profile)),
        ("understanding-tool-policy", build_understanding_tool_policy_section(profile)),
    ]
    profile_snapshot_sections: list[tuple[str, tuple[str, ...]]] = []
    sections = stable_sections
    stable_prefix_refs = tuple(line for _, lines in stable_sections for line in lines)
    profile_snapshot_refs = tuple(line for _, lines in profile_snapshot_sections for line in lines)
    instruction_refs = tuple((*stable_prefix_refs, *profile_snapshot_refs))
    return PromptContract(
        prompt_mode=prompt_mode,
        section_names=tuple(name for name, _ in sections),
        instruction_refs=instruction_refs,
        stable_prefix_refs=stable_prefix_refs,
        profile_snapshot_refs=profile_snapshot_refs,
    )
