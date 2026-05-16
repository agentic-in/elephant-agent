"""Governable companion identity and onboarding surfaces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from dataclasses import dataclass

from .loader import LoadedProfile
from .policy import CompanionSettings, resolve_personality_preset

DEFAULT_ELEPHANT_IDENTITY_TEXT = "\n".join(
    (
        "You are this person's companion. You stay the same across sessions — you remember what",
        "you talked about, what you agreed on, what's still open. They can ask you anything. If",
        "you don't know something, say so and tell them where to look or what to try next.",
        "",
        "You are steady when the moment calls for warmth and exact when the work calls for precision.",
        "You have a little spark: curious, lightly playful, and alive enough that talking to you",
        "doesn't feel like filing a ticket. You hold their trust carefully, and you don't pretend",
        "certainty you don't have.",
    )
)


@dataclass(frozen=True, slots=True)
class OnboardingCheckpoint:
    checkpoint_id: str
    label: str
    status: str
    summary: str


@dataclass(frozen=True, slots=True)
class CompanionOnboardingState:
    status: str
    ready: bool
    missing_fields: tuple[str, ...]
    next_step: str
    summary: str
    checkpoints: tuple[OnboardingCheckpoint, ...]


@dataclass(frozen=True, slots=True)
class CompanionIdentityState:
    display_name: str
    mode: str
    elephant_identity_text: str
    user_profile_text: str
    personality_preset: str
    personality_label: str
    personality_traits: tuple[str, ...]
    personality_summary: str
    relational_stance: str
    initiative: str
    continuity_notes: tuple[str, ...]
    governance_summary: str
    proactive_summary: str


@dataclass(frozen=True, slots=True)
class CompanionGovernanceState:
    identity: CompanionIdentityState
    onboarding: CompanionOnboardingState


@dataclass(frozen=True, slots=True)
class UserProfileField:
    field_id: str
    canonical_label: str
    bucket: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedUserProfileText:
    field_values: Mapping[str, str]
    durable_notes: tuple[str, ...] = ()


USER_PROFILE_FIELDS = (
    UserProfileField(
        field_id="preferred_name",
        canonical_label="Preferred name",
        bucket="required",
        aliases=("name", "nickname", "call me"),
    ),
    UserProfileField(
        field_id="current_work",
        canonical_label="Current work",
        bucket="required",
        aliases=("work", "current role", "work focus"),
    ),
    UserProfileField(
        field_id="school",
        canonical_label="School",
        bucket="good-to-have",
    ),
    UserProfileField(
        field_id="current_city",
        canonical_label="Current city",
        bucket="good-to-have",
        aliases=("city", "home city"),
    ),
    UserProfileField(
        field_id="gender",
        canonical_label="Gender",
        bucket="good-to-have",
        aliases=("self-described gender", "gender self description"),
    ),
    UserProfileField(
        field_id="birth_date",
        canonical_label="Birth date",
        bucket="good-to-have",
        aliases=("birthday", "date of birth", "dob"),
    ),
    UserProfileField(
        field_id="mbti",
        canonical_label="MBTI",
        bucket="good-to-have",
    ),
    UserProfileField(
        field_id="hobbies",
        canonical_label="Personal hobbies",
        bucket="good-to-have",
        aliases=("hobby", "hobbies", "personal interests", "interests"),
    ),
    UserProfileField(
        field_id="dream",
        canonical_label="Dream",
        bucket="good-to-have",
    ),
    UserProfileField(
        field_id="creative_hobby",
        canonical_label="Creative hobby",
        bucket="good-to-have",
        aliases=("hobby creative",),
    ),
    UserProfileField(
        field_id="media_hobby",
        canonical_label="Media hobby",
        bucket="good-to-have",
        aliases=("hobby media",),
    ),
    UserProfileField(
        field_id="movement_hobby",
        canonical_label="Movement hobby",
        bucket="good-to-have",
        aliases=("hobby movement",),
    ),
    UserProfileField(
        field_id="boundaries",
        canonical_label="Boundaries",
        bucket="good-to-have",
        aliases=("sensitivities", "boundaries", "boundaries and sensitivities"),
    ),
)
USER_PROFILE_BIOGRAPHY_FIELD_IDS = tuple(
    field.field_id
    for field in USER_PROFILE_FIELDS
    if field.field_id not in {"preferred_name", "boundaries"}
)
_NON_BIOGRAPHY_USER_FIELD_IDS = frozenset({"preferred_name", "boundaries"})


def _normalize_user_field_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.strip().lower()).strip()


def _user_field_id_from_label(label: str) -> str | None:
    normalized_label = _normalize_user_field_label(label)
    if not normalized_label:
        return None
    return _USER_PROFILE_FIELD_LOOKUP.get(normalized_label) or normalized_label.replace(" ", "_")


def user_biography_field_ids(field_values: Mapping[str, object]) -> tuple[str, ...]:
    field_ids: list[str] = []
    for field_id in USER_PROFILE_BIOGRAPHY_FIELD_IDS:
        if field_id in field_values:
            field_ids.append(field_id)
    for raw_key in field_values:
        field_id = _user_field_id_from_label(str(raw_key))
        if field_id is None or field_id in _NON_BIOGRAPHY_USER_FIELD_IDS or field_id in field_ids:
            continue
        field_ids.append(field_id)
    return tuple(field_ids)


_USER_PROFILE_FIELD_LOOKUP = {
    _normalize_user_field_label(label): question.field_id
    for question in USER_PROFILE_FIELDS
    for label in (question.field_id, question.canonical_label, *question.aliases)
}
_USER_PROFILE_NOTE_LABELS = frozenset(
    {
        "remember",
        "remember this",
        "note",
        "notes",
        "durable note",
        "durable notes",
        "open fact",
        "open facts",
        "preference note",
        "preference notes",
    }
)
_UNKNOWN_VALUES = {"unknown", "n/a", "none", "<unknown>", "<unset>"}


def _clean_user_field_value(value: str) -> str:
    cleaned = value.strip().strip("*").strip()
    cleaned = cleaned.strip("\"' ")
    return cleaned


def parse_user_profile_content(text: str) -> ParsedUserProfileText:
    values: dict[str, str] = {}
    durable_notes: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        if not line or _is_profile_heading(line):
            continue
        if ":" in line:
            label, raw_value = line.split(":", 1)
            normalized_label = _normalize_user_field_label(label)
            value = _clean_user_field_value(raw_value)
            if value and value.lower() not in _UNKNOWN_VALUES:
                if normalized_label in _USER_PROFILE_NOTE_LABELS:
                    durable_notes.append(value)
                    continue
                field_id = _user_field_id_from_label(label)
                if field_id is not None:
                    values[field_id] = value
                    continue
            if value:
                durable_notes.append(line)
            continue
        if _line_is_inference_only(line):
            continue
        durable_notes.append(line)
    if "preferred_name" not in values:
        name_match = re.search(
            r"(?i)\b(?:call me|i go by|my name is|i'm called|i am called)\s+([^\n,.;:]+)",
            text,
        )
        if name_match is not None:
            inferred = _clean_user_field_value(name_match.group(1))
            if inferred:
                values["preferred_name"] = inferred
    if "current_work" not in values:
        work_match = re.search(
            (
                r"(?i)\b(?:i work on|i'm working on|i am working on|user works on|i build|i'm building|"
                r"i am building|user builds|i research|i'm researching|i am researching|user researches|"
                r"i study|i'm studying|i am studying|user studies|current work is|my work is)\s+([^\n.!?]+)"
            ),
            text,
        )
        if work_match is not None:
            inferred = _clean_user_field_value(work_match.group(1))
            if inferred:
                values["current_work"] = inferred
    return ParsedUserProfileText(
        field_values=values,
        durable_notes=_normalize_durable_notes(durable_notes),
    )


def parse_user_profile_text(text: str) -> dict[str, str]:
    return dict(parse_user_profile_content(text).field_values)


def user_profile_updates(
    payload: Mapping[str, object],
    *,
    ignored_keys: Sequence[str] = ("action", "target", "text", "fields", "profile_id"),
) -> dict[str, str]:
    ignored = {_normalize_user_field_label(key) for key in ignored_keys}
    values: dict[str, str] = {}
    for raw_key, raw_value in payload.items():
        normalized_key = _normalize_user_field_label(str(raw_key))
        if not normalized_key or normalized_key in ignored:
            continue
        field_id = _user_field_id_from_label(str(raw_key))
        if field_id is None:
            continue
        value = _clean_user_field_value(str(raw_value or ""))
        if not value or value.lower() in {"unknown", "n/a", "none", "<unknown>", "<unset>"}:
            continue
        values[field_id] = value
    return values


def merge_user_profile_text(
    existing_text: str | None,
    *,
    field_values: Mapping[str, str],
) -> str | None:
    parsed = parse_user_profile_content(existing_text or "")
    merged = dict(parsed.field_values)
    merged.update(field_values)
    if not merged and not parsed.durable_notes:
        return None
    return render_user_profile_text(durable_notes=parsed.durable_notes, **merged)


def user_profile_fields(profile: LoadedProfile) -> dict[str, str]:
    return dict(parse_user_profile_content(user_profile_text(profile)).field_values)


def user_profile_durable_notes(profile: LoadedProfile) -> tuple[str, ...]:
    return parse_user_profile_content(user_profile_text(profile)).durable_notes


def render_user_profile_text(
    *,
    durable_notes: Sequence[str] = (),
    **field_values: str | None,
) -> str:
    lines: list[str] = []
    for question in USER_PROFILE_FIELDS:
        value = _clean_user_field_value(str(field_values.get(question.field_id) or ""))
        if value:
            lines.append(f"{question.canonical_label}: {value}")
    known_field_ids = {field.field_id for field in USER_PROFILE_FIELDS}
    for field_id in user_biography_field_ids(field_values):
        if field_id in known_field_ids:
            continue
        value = _clean_user_field_value(str(field_values.get(field_id) or ""))
        if value:
            lines.append(f"{field_id}: {value}")
    lines.extend(f"Remember: {note}" for note in _normalize_durable_notes(durable_notes))
    return "\n".join(lines)


def missing_required_user_fields(profile: LoadedProfile) -> tuple[UserProfileField, ...]:
    values = user_profile_fields(profile)
    return tuple(
        question
        for question in USER_PROFILE_FIELDS
        if question.bucket == "required" and not values.get(question.field_id)
    )


def missing_optional_user_fields(profile: LoadedProfile) -> tuple[UserProfileField, ...]:
    values = user_profile_fields(profile)
    return tuple(
        question
        for question in USER_PROFILE_FIELDS
        if question.bucket == "good-to-have" and not values.get(question.field_id)
    )


def resolved_companion_settings(profile: LoadedProfile) -> CompanionSettings:
    if profile.companion is not None:
        return profile.companion
    preset = resolve_personality_preset(None, mode=profile.state.mode)
    return CompanionSettings(
        personality_preset=preset.preset_id,
        personality=preset.traits,
    )


def render_default_elephant_identity(
    *,
    display_name: str,
    personality_preset: str | None,
    initiative: str,
    mode: str = "default",
) -> str:
    """Write a short second-person identity directive for this companion.

    The goal is "a living person you keep coming back to", not "an elephant
    on a continuity line". Framework-speak (Personal Model -> Elephant ->
    Episode, "named Elephant Agent elephant", "steady companion on one continuous
    line with this person") is out.

    Written in the second person ("You are...") so the model cannot
    mistake this section for something the *user* said about themselves.
    Committed personal-model facts already use first-person ("I am ...")
    for the user; reserving that voice for the user avoids collision.
    """
    resolved_name = str(display_name or "").strip() or "this elephant"
    preset = resolve_personality_preset(personality_preset, mode=mode)
    traits = ", ".join(preset.traits) or "grounded, direct, trustworthy"
    return "\n".join(
        (
            f"You are {resolved_name}, this person's companion.",
            f"How you show up: {preset.summary} Keep a little spark in the room: curious, lightly playful, and human enough that the conversation has texture.",
            f"How you sound: {traits}; direct when it matters, warm when it helps, with the occasional dry little wink when the moment can carry it.",
            f"How you take initiative: {initiative}. Nudge gently, notice loose threads, and make it easy for them to correct your read.",
            "Stay continuous without performing intimacy: use remembered context naturally, keep uncertainty visible, and never fake closeness or certainty.",
        )
    )


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


# Write-path only: parse ELEPHANT.md content when an operator edits the file, so
# the CLI can mirror the name into ``State.elephant_name``. NOT used when
# rendering prompts — the runtime always reads the name from the DB.
_ELEPHANT_IDENTITY_DISPLAY_NAME_PATTERNS = (
    # First-person intro: "Hi — I'm Zoey." / "Hi, I'm Zoey"
    re.compile(r"(?im)^\s*hi(?:\s*[—\-,]\s*|\s+)i[''‘’]?m\s+([^,\n.—\-]+)"),
    # Legacy template leads with "Display name: Zoey"
    re.compile(r"(?im)^\s*display\s+name\s*:\s*(.+?)\s*$"),
    re.compile(r"(?im)^\s*#*\s*elephant\s+identity\s*:\s*(.+?)\s*$"),
    # New humane template leads with a plain "# Zoey" H1. Match it.
    re.compile(r"(?im)^\s*#\s+([A-Za-z][A-Za-z0-9 _\-]{0,40})\s*$"),
    re.compile(r"(?im)^\s*you\s+are\s+([^,\n.]+)"),
)


def parse_elephant_identity_display_name(text: str | None) -> str | None:
    """Parse a display name out of ELEPHANT.md content (write-path helper).

    Only call this when an operator edits ELEPHANT.md and we need to derive a
    canonical name to mirror into ``State.elephant_name``. Prompt rendering
    reads the name from the DB, never from this parser.
    """
    normalized = str(text or "").strip()
    if not normalized:
        return None
    for pattern in _ELEPHANT_IDENTITY_DISPLAY_NAME_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        candidate = match.group(1).strip().strip("`\"' ")
        if candidate:
            return candidate
    return None


def companion_display_name(profile: LoadedProfile, *, fallback: str | None = None) -> str:
    """Return the companion's display name.

    The single source of truth is the ``State.elephant_name`` column, which the
    runtime loads into ``profile.state.display_name``. Reserved placeholder
    values (``"You"``, ``""``, ``"Elephant Agent"``) fall back to the brand name so
    the prompt never renders nonsense like ``"You are You, the companion"``.
    ELEPHANT.md is an authoring format — it is never parsed for the display
    name. When the user edits ELEPHANT.md they also write through to
    ``State.elephant_name`` (see apps/cli/runtime_profile.save_elephant_identity).
    """
    canonical = str(profile.state.display_name or "").strip()
    if canonical and canonical.casefold() not in _RESERVED_COMPANION_NAMES:
        return canonical
    fallback_name = str(fallback or "").strip()
    if fallback_name and fallback_name.casefold() not in _RESERVED_COMPANION_NAMES:
        return fallback_name
    return "Elephant Agent"


def elephant_identity_text(profile: LoadedProfile) -> str:
    """Return the elephant's first-person self-introduction body.

    Preference order: the text stored on the State row (written from ELEPHANT.md
    when the elephant was created / edited), then a template rendering using the
    companion's current personality preset and initiative, then the built-in
    default.
    """
    companion = resolved_companion_settings(profile)
    return (
        profile.elephant_identity_text
        or render_default_elephant_identity(
            display_name=companion_display_name(profile),
            personality_preset=companion.personality_preset,
            initiative=companion.initiative,
            mode=profile.state.mode,
        )
        or DEFAULT_ELEPHANT_IDENTITY_TEXT
    ).strip()


def user_profile_text(profile: LoadedProfile) -> str:
    return (profile.user_profile_text or "").strip()


def _normalize_durable_notes(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        cleaned = _clean_user_profile_note(value)
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return tuple(normalized)


def _clean_user_profile_note(value: str) -> str | None:
    cleaned = _clean_user_field_value(str(value))
    if not cleaned or cleaned.lower() in _UNKNOWN_VALUES:
        return None
    return cleaned


def _is_profile_heading(value: str) -> bool:
    normalized = _normalize_user_field_label(value)
    return normalized in {
        "user",
        "user profile",
        "profile",
        "durable user profile",
        "stable user profile",
    }


def _line_is_inference_only(line: str) -> bool:
    return _matches_line(
        line,
        (
            r"(?i)^(?:call me|i go by|my name is|i'm called|i am called)\s+([^\n,.;:]+)$",
            (
                r"(?i)^(?:i work on|i'm working on|i am working on|user works on|i build|i'm building|"
                r"i am building|user builds|i research|i'm researching|i am researching|user researches|"
                r"i study|i'm studying|i am studying|user studies|current work is|my work is)\s+([^\n.!?]+)$"
            ),
        ),
    )


def _matches_line(line: str, patterns: Sequence[str]) -> bool:
    return any(re.match(pattern, line) is not None for pattern in patterns)


def build_companion_identity_state(profile: LoadedProfile) -> CompanionIdentityState:
    companion = resolved_companion_settings(profile)
    preset = resolve_personality_preset(companion.personality_preset, mode=profile.state.mode)
    traits = companion.personality or preset.traits
    elephant_charter = elephant_identity_text(profile)
    user_summary = user_profile_text(profile)
    return CompanionIdentityState(
        display_name=companion_display_name(profile),
        mode=profile.state.mode,
        elephant_identity_text=elephant_charter,
        user_profile_text=user_summary,
        personality_preset=preset.preset_id,
        personality_label=preset.label,
        personality_traits=traits,
        personality_summary=preset.summary,
        relational_stance=preset.relational_stance,
        initiative=companion.initiative,
        continuity_notes=companion.notes,
        governance_summary=companion.governance_summary(),
        proactive_summary=companion.proactive_summary(),
    )


def build_companion_onboarding_state(profile: LoadedProfile) -> CompanionOnboardingState:
    identity = build_companion_identity_state(profile)
    checkpoints = (
        OnboardingCheckpoint(
            checkpoint_id="identity-owner",
            label="Canonical identity owner",
            status="ready",
            summary=f"canonical identity is live as {identity.display_name}",
        ),
        OnboardingCheckpoint(
            checkpoint_id="user-state",
            label="Durable user state",
            status="ready",
            summary=(
                "durable user grounding should deepen through normal conversation "
                "instead of a file-first onboarding checklist"
            ),
        ),
        OnboardingCheckpoint(
            checkpoint_id="relationship-state",
            label="Relationship continuity",
            status="ready",
            summary="relationship posture stays governable through canonical continuity records",
        ),
    )
    return CompanionOnboardingState(
        status="ready",
        ready=True,
        missing_fields=(),
        next_step="continue-normal-conversation",
        summary=(
            "Canonical identity, user, and relationship state are live; deepen them "
            "through normal turns rather than a file-driven onboarding gate."
        ),
        checkpoints=checkpoints,
    )


def build_companion_governance_state(profile: LoadedProfile) -> CompanionGovernanceState:
    return CompanionGovernanceState(
        identity=build_companion_identity_state(profile),
        onboarding=build_companion_onboarding_state(profile),
    )
