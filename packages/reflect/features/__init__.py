"""Reflect feature registry.

Each feature module exposes a Feature instance via FEATURE.
"""

from __future__ import annotations

from .types import Feature
from .pm import FEATURE as PM
from .questions import FEATURE as QUESTIONS
from .recall import FEATURE as RECALL
from .diary import FEATURE as DIARY
from .skills import FEATURE as SKILLS
from .compress import FEATURE as COMPRESS
from .dream import FEATURE as DREAM
from .init_links import FEATURE as INIT_LINKS
from .onboarding_letter import FEATURE as ONBOARDING_LETTER
from .skill_optimization import FEATURE as SKILL_EVOLUTION


ALL_FEATURES: dict[str, Feature] = {
    f.feature_id: f
    for f in (PM, QUESTIONS, RECALL, DIARY, SKILLS, COMPRESS, DREAM, INIT_LINKS, ONBOARDING_LETTER, SKILL_EVOLUTION)
}

# Canonical trigger → default feature set mapping. Keep this small: triggers
# explain why a job runs, while features explain what the job may write.
TRIGGER_FEATURES: dict[str, tuple[str, ...]] = {
    "episode_close": ("pm", "questions", "skill_affinity"),
    "manual": ("pm", "questions", "skill_affinity"),
    "diary": ("diary",),
    "dream": ("dream", "questions", "skill_affinity", "skill_evolution", "diary"),
    "skill_review": ("skill_evolution", "skill_affinity"),
    "init": ("init_links", "pm", "questions", "skill_affinity"),
    "init_profile": ("init_links", "pm", "questions", "skill_affinity"),
    "onboarding_letter": ("onboarding_letter",),
    "context_compaction": ("compress",),
}

FEATURE_ALIASES: dict[str, tuple[str, ...]] = {
    "skills": ("skill_affinity",),
    "skill_optimization": ("skill_evolution",),
    "skill_creation": ("skill_evolution",),
    "skill_create": ("skill_evolution",),
    "profile": ("init_links", "pm", "questions", "skill_affinity"),
    "init_profile": ("init_links", "pm", "questions", "skill_affinity"),
    "letter": ("onboarding_letter",),
}

# Conservatism levels per trigger (affects system prompt tone)
TRIGGER_CONSERVATISM: dict[str, str] = {
    "episode_close": "medium",
    "manual": "low",
    "diary": "creative",
    "dream": "medium",
    "skill_review": "medium",
    "init": "low",
    "init_profile": "low",
    "onboarding_letter": "creative",
    "context_compaction": "high",
}


def resolve_features(
    trigger: str,
    *,
    explicit_features: tuple[str, ...] | None = None,
) -> tuple[Feature, ...]:
    """Resolve which features to activate for a given trigger.

    If explicit_features is provided (from CLI --features flag), use those
    instead of the trigger's default mapping.
    """

    if explicit_features:
        expanded: list[str] = []
        for feature_id in explicit_features:
            alias = FEATURE_ALIASES.get(feature_id)
            if alias is not None:
                expanded.extend(alias)
            else:
                expanded.append(feature_id)
        feature_ids = tuple(dict.fromkeys(expanded))
        if "dream" in feature_ids:
            feature_ids = tuple(
                fid
                for fid in ("dream", "questions", "skill_affinity", "skill_evolution", "diary")
                if fid in feature_ids
            )
            if trigger == "dream":
                for bundled_feature in ("questions", "skill_affinity", "skill_evolution", "diary"):
                    if bundled_feature not in feature_ids:
                        feature_ids = (*feature_ids, bundled_feature)
    else:
        feature_ids = TRIGGER_FEATURES.get(trigger, TRIGGER_FEATURES["manual"])

    features = []
    for fid in feature_ids:
        feature = ALL_FEATURES.get(fid)
        if feature is not None:
            features.append(feature)

    resolved_ids = {feature.feature_id for feature in features}
    for feature in list(features):
        for req in feature.requires:
            if req not in resolved_ids:
                dependency = ALL_FEATURES.get(req)
                if dependency is not None:
                    features.append(dependency)
                    resolved_ids.add(req)

    for feature in tuple(features):
        for incompat in feature.incompatible:
            if incompat in resolved_ids and incompat != feature.feature_id:
                features = [item for item in features if item.feature_id not in feature.incompatible]
                break

    return tuple(features)
