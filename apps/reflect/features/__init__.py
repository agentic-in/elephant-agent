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


ALL_FEATURES: dict[str, Feature] = {
    f.feature_id: f for f in (PM, QUESTIONS, RECALL, DIARY, SKILLS, COMPRESS, DREAM, INIT_LINKS)
}

# Trigger → default feature set mapping
TRIGGER_FEATURES: dict[str, tuple[str, ...]] = {
    "episode_close": ("pm", "questions", "skills"),
    "manual": ("pm", "questions", "recall", "skills"),
    "diary": ("diary",),
    "dream": ("dream", "questions", "skills", "diary"),
    "init": ("pm", "questions", "skills", "init_links"),
    "init_profile": ("pm", "questions", "skills", "init_links"),
    "context_compaction": ("compress",),
}

FEATURE_ALIASES: dict[str, tuple[str, ...]] = {
    "profile": ("pm", "questions", "skills", "init_links"),
    "init_profile": ("pm", "questions", "skills", "init_links"),
}

# Conservatism levels per trigger (affects system prompt tone)
TRIGGER_CONSERVATISM: dict[str, str] = {
    "episode_close": "medium",
    "manual": "low",
    "diary": "creative",
    "dream": "medium",
    "init": "low",
    "init_profile": "low",
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
            feature_ids = tuple(fid for fid in ("dream", "questions", "skills", "diary") if fid in feature_ids)
            if trigger == "dream":
                for bundled_feature in ("skills", "diary"):
                    if bundled_feature not in feature_ids:
                        feature_ids = (*feature_ids, bundled_feature)
    else:
        feature_ids = TRIGGER_FEATURES.get(trigger, ("pm", "questions", "skills"))

    features = []
    for fid in feature_ids:
        feature = ALL_FEATURES.get(fid)
        if feature is not None:
            features.append(feature)
    # Resolve REQUIRES dependencies
    resolved_ids = {f.feature_id for f in features}
    for feature in list(features):
        for req in feature.requires:
            if req not in resolved_ids:
                dep = ALL_FEATURES.get(req)
                if dep is not None:
                    features.append(dep)
                    resolved_ids.add(req)
    # Validate INCOMPATIBLE
    for feature in features:
        for incompat in feature.incompatible:
            if incompat in resolved_ids and incompat != feature.feature_id:
                # Drop incompatible features silently (exclusive feature wins)
                features = [f for f in features if f.feature_id not in feature.incompatible]
                break
    return tuple(features)
