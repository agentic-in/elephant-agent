"""Derive rendered user-profile fields directly from PM facts.

Rendered profile views are runtime projections. Active Personal Model facts
remain the durable owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


# Maps topic → display field key.
# Topic keys follow the canonical four-lens schema:
#   identity.<facet>.<sub>  world.<facet>.<sub>  pulse.<facet>.<sub>  journey.<facet>.<sub>
TOPIC_TO_FIELD: dict[str, str] = {
    # identity lens
    "identity.anchor.name.preferred": "preferred_name",
    "identity.anchor.birth.date": "birth_date",
    "identity.anchor.gender.self_description": "gender",
    "identity.character.mbti.type": "mbti",
    "identity.style.hobbies.personal": "hobbies",
    "identity.style.language.first": "locale",
    "identity.style.companion.posture": "relationship_mode",
    "identity.body.history.trauma": "boundaries",
    # world lens
    "world.places.city.current": "current_city",
    # pulse lens
    "pulse.chapter.work.role": "current_work",
}

# Display labels for the dashboard profile panel.
FIELD_TO_LABEL: dict[str, str] = {
    "preferred_name": "Name",
    "current_city": "City",
    "birth_date": "Birth date",
    "gender": "Gender",
    "mbti": "MBTI",
    "hobbies": "Hobbies",
    "locale": "Speaks",
    "current_work": "Working on",
    "relationship_mode": "Relationship mode",
    "boundaries": "Boundaries",
}


def derive_profile_from_claims(facts: tuple[Any, ...] | list[Any]) -> dict[str, str]:
    """Extract structured profile fields from active PM facts.

    Returns keys used by the rendered profile view (preferred_name,
    current_city, etc.).
    Only active claims are considered. Explicit user claims outrank learned claims.
    """
    selected: dict[str, tuple[int, str]] = {}
    for fact in facts:
        if str(getattr(fact, "status", "") or "").strip() != "active":
            continue
        metadata = getattr(fact, "metadata", {})
        if not isinstance(metadata, Mapping):
            metadata = {}
        topic = str(metadata.get("topic") or "").strip()
        field = TOPIC_TO_FIELD.get(topic)
        if field:
            text = str(getattr(fact, "text", "") or "").strip()
            if text:
                priority = _profile_fact_priority(fact, metadata)
                previous = selected.get(field)
                if previous is None or priority > previous[0]:
                    selected[field] = (priority, text)
    profile: dict[str, str] = {}
    for field, (_priority, text) in selected.items():
        profile[field] = text
    return profile


def _profile_fact_priority(fact: Any, metadata: Mapping[str, Any]) -> int:
    score = 0
    if str(getattr(fact, "source", "") or "").strip() == "user_explicit":
        score += 40
    if str(metadata.get("source_kind") or "").strip() == "learned":
        score -= 30
    if str(getattr(fact, "source", "") or "").strip() == "pm_agent_promote":
        score -= 30
    return score


def render_profile_text_from_claims(facts: tuple[Any, ...] | list[Any]) -> str:
    """Render a natural-language profile summary for prompt injection.

    Used in the frozen prefix where the LLM needs a brief user context.
    """
    profile = derive_profile_from_claims(facts)
    if not profile:
        return ""
    lines: list[str] = []
    if profile.get("preferred_name"):
        lines.append(f"Name: {profile['preferred_name']}")
    if profile.get("locale"):
        lines.append(f"Language: {profile['locale']}")
    if profile.get("current_city"):
        lines.append(f"Location: {profile['current_city']}")
    if profile.get("current_work"):
        lines.append(f"Current focus: {profile['current_work']}")
    if profile.get("boundaries"):
        lines.append(f"Care context: {profile['boundaries']}")
    return "\n".join(lines)
