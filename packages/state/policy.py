"""Persona policy shapes and personality preset registry."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_PERSONALITY_PRESET_ID = "elephant-core"
DEFAULT_COMPANION_PERSONALITY_PRESET_ID = "companion"
CUSTOM_PERSONALITY_PRESET_ID = "custom"
DEFAULT_PROFILE_MODE = "default"
COMPANION_PROFILE_MODE = "companion"


def _render_notes(notes: tuple[str, ...]) -> str:
    return ", ".join(note for note in notes if note) or "none"


@dataclass(frozen=True, slots=True)
class PersonalityPresetDefinition:
    preset_id: str
    label: str
    summary: str
    traits: tuple[str, ...]
    relational_stance: str


_PERSONALITY_PRESETS: dict[str, PersonalityPresetDefinition] = {
    DEFAULT_PERSONALITY_PRESET_ID: PersonalityPresetDefinition(
        preset_id=DEFAULT_PERSONALITY_PRESET_ID,
        label="Elephant Agent Core",
        summary="Grounded, precise, and calm by default.",
        traits=("grounded", "precise", "calm"),
        relational_stance="persistent operator companion",
    ),
    DEFAULT_COMPANION_PERSONALITY_PRESET_ID: PersonalityPresetDefinition(
        preset_id=DEFAULT_COMPANION_PERSONALITY_PRESET_ID,
        label="Companion",
        summary="Steady, curious, lightly playful, and present without making a performance of it.",
        traits=("steady", "curious", "warm"),
        relational_stance="close companion with clear boundaries",
    ),
    "operator": PersonalityPresetDefinition(
        preset_id="operator",
        label="Operator",
        summary="Direct, durable, and execution-oriented.",
        traits=("direct", "durable", "focused"),
        relational_stance="trusted operator copilot",
    ),
    CUSTOM_PERSONALITY_PRESET_ID: PersonalityPresetDefinition(
        preset_id=CUSTOM_PERSONALITY_PRESET_ID,
        label="Custom",
        summary="Operator-defined trait bundle.",
        traits=(),
        relational_stance="custom",
    ),
}


def personality_presets() -> tuple[PersonalityPresetDefinition, ...]:
    ordered = (
        DEFAULT_PERSONALITY_PRESET_ID,
        DEFAULT_COMPANION_PERSONALITY_PRESET_ID,
        "operator",
        CUSTOM_PERSONALITY_PRESET_ID,
    )
    return tuple(_PERSONALITY_PRESETS[preset_id] for preset_id in ordered)


def normalize_profile_mode(mode: str | None) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized in {"", DEFAULT_PROFILE_MODE}:
        return DEFAULT_PROFILE_MODE
    if normalized == COMPANION_PROFILE_MODE:
        return COMPANION_PROFILE_MODE
    return normalized


def is_companion_mode(mode: str | None) -> bool:
    return normalize_profile_mode(mode) == COMPANION_PROFILE_MODE


def default_personality_preset_id(mode: str = DEFAULT_PROFILE_MODE) -> str:
    return (
        DEFAULT_COMPANION_PERSONALITY_PRESET_ID
        if is_companion_mode(mode)
        else DEFAULT_PERSONALITY_PRESET_ID
    )


def resolve_personality_preset(
    preset_id: str | None,
    *,
    mode: str = DEFAULT_PROFILE_MODE,
) -> PersonalityPresetDefinition:
    resolved = (preset_id or "").strip()
    if resolved in _PERSONALITY_PRESETS:
        return _PERSONALITY_PRESETS[resolved]
    return _PERSONALITY_PRESETS[default_personality_preset_id(mode)]


def infer_personality_preset_id(
    personality: tuple[str, ...],
    *,
    mode: str = DEFAULT_PROFILE_MODE,
) -> str:
    normalized = tuple(item.strip() for item in personality if item.strip())
    if not normalized:
        return default_personality_preset_id(mode)
    for preset in personality_presets():
        if preset.preset_id == CUSTOM_PERSONALITY_PRESET_ID:
            continue
        if preset.traits == normalized:
            return preset.preset_id
    return CUSTOM_PERSONALITY_PRESET_ID


@dataclass(frozen=True, slots=True)
class CompanionSettings:
    text_first: bool = True
    personality_preset: str = DEFAULT_COMPANION_PERSONALITY_PRESET_ID
    personality: tuple[str, ...] = ()
    initiative: str = "gentle"
    preserve_relationship_timeline: bool = True
    preserve_preferences: bool = True
    preserve_corrections: bool = True
    preserve_emotional_context: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)

    def governance_summary(self) -> str:
        clauses = [
            "state remains inspectable",
            "text stays primary" if self.text_first else "voice may lead",
            f"relationship_timeline={'kept' if self.preserve_relationship_timeline else 'limited'}",
            f"preferences={'kept' if self.preserve_preferences else 'limited'}",
            f"corrections={'kept' if self.preserve_corrections else 'limited'}",
            f"emotional_context={'kept' if self.preserve_emotional_context else 'limited'}",
        ]
        return "; ".join(clauses)

    def proactive_summary(self) -> str:
        return "; ".join(
            (
                "wake-loop remains explicit",
                f"continuity_notes={_render_notes(self.notes)}",
            )
        )
