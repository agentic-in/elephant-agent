"""Canonical continuity-state and relationship-policy helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re

from packages.contracts.layers import Episode
from packages.contracts.runtime import EpisodeContinuityState


@dataclass(frozen=True, slots=True)
class RelationshipPolicy:
    profile_mode: str
    text_first: bool = True
    preserve_relationship_timeline: bool = True
    preserve_preferences: bool = True
    preserve_corrections: bool = True
    preserve_emotional_context: bool = True
    allowed_signal_kinds: tuple[str, ...] = ("relationship", "preference", "continuity")

    def allows(self, signal_kind: str) -> bool:
        return signal_kind in self.allowed_signal_kinds

    def summary(self) -> str:
        posture = "text-first" if self.text_first else "multi-modal"
        return (
            f"{self.profile_mode} {posture} continuity: "
            f"timeline={self.preserve_relationship_timeline}, "
            f"preferences={self.preserve_preferences}, "
            f"corrections={self.preserve_corrections}, "
            f"emotional={self.preserve_emotional_context}"
        )


@dataclass(frozen=True, slots=True)
class _NormalizedInterruptionState:
    value: str | None
    generated_resume: bool = False


_AFTER_INTERRUPTION_MARKER = " after interruption: "
_RECOVER_INTERRUPTION_PREFIX = "recover after interruption: "
_RESUME_SUMMARY_PREFIX = "resume durable work from episode "
_GENERATED_SUFFIX_PREFIXES = ("active elephant focus ", "immediate parent=")


def build_episode_continuity_state(
    episode: Episode,
    *,
    lineage: tuple[Episode, ...] = (),
) -> EpisodeContinuityState:
    chain = lineage or (episode,)
    lineage_episode_ids = tuple(node.episode_id for node in chain)
    origin_episode_id = (
        lineage_episode_ids[0] if lineage_episode_ids else (episode.parent_episode_id or episode.episode_id)
    )
    inherited_interruption_state = normalize_interruption_state(episode.interruption_state)
    if inherited_interruption_state is None:
        for ancestor in reversed(chain[:-1]):
            normalized = normalize_interruption_state(ancestor.interruption_state)
            if normalized is not None:
                inherited_interruption_state = normalized
                break

    if episode.parent_episode_id and inherited_interruption_state is not None:
        mode = "background"
    elif episode.parent_episode_id:
        mode = "resumed"
    elif inherited_interruption_state is not None:
        mode = "interrupted"
    else:
        mode = "foreground"

    summary = _continuity_summary(
        mode=mode,
        episode=episode,
        origin_episode_id=origin_episode_id,
        inherited_interruption_state=inherited_interruption_state,
    )
    return EpisodeContinuityState(
        episode_id=episode.episode_id,
        mode=mode,
        origin_episode_id=origin_episode_id,
        lineage_episode_ids=lineage_episode_ids,
        inherited_interruption_state=inherited_interruption_state,
        summary=summary,
    )


def apply_episode_continuity_state(
    episode: Episode,
    continuity: EpisodeContinuityState,
) -> Episode:
    normalized = _normalize_interruption_state(episode.interruption_state)
    if normalized.generated_resume or normalized.value != episode.interruption_state:
        return replace(episode, interruption_state=normalized.value)
    if episode.interruption_state is not None:
        return episode
    if not continuity.requires_recovery:
        return episode
    return replace(episode, interruption_state=continuity.inherited_interruption_state)


def build_relationship_policy(
    profile_mode: str,
    *,
    text_first: bool = True,
    preserve_relationship_timeline: bool = True,
    preserve_preferences: bool = True,
    preserve_corrections: bool = True,
    preserve_emotional_context: bool = True,
    allowed_signal_kinds: tuple[str, ...] = (
        "relationship",
        "preference",
        "continuity",
    ),
) -> RelationshipPolicy:
    return RelationshipPolicy(
        profile_mode=profile_mode,
        text_first=text_first,
        preserve_relationship_timeline=preserve_relationship_timeline,
        preserve_preferences=preserve_preferences,
        preserve_corrections=preserve_corrections,
        preserve_emotional_context=preserve_emotional_context,
        allowed_signal_kinds=allowed_signal_kinds,
    )


def normalize_interruption_state(value: str | None) -> str | None:
    return _normalize_interruption_state(value).value


def _compact_interruption_text(value: str | None) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def _strip_generated_suffixes(value: str | None) -> str | None:
    text = _compact_interruption_text(value)
    if text is None:
        return None
    parts = [part.strip() for part in text.split(";")]
    kept = [part for part in parts[:1] if part]
    kept.extend(part for part in parts[1:] if part and not part.startswith(_GENERATED_SUFFIX_PREFIXES))
    return _compact_interruption_text("; ".join(kept))


def _normalize_interruption_state(value: str | None) -> _NormalizedInterruptionState:
    text = _compact_interruption_text(value)
    generated_resume = False
    for _ in range(12):
        if text is None:
            return _NormalizedInterruptionState(None, generated_resume=generated_resume)
        if text.startswith(_RECOVER_INTERRUPTION_PREFIX):
            generated_resume = True
            text = _strip_generated_suffixes(text.removeprefix(_RECOVER_INTERRUPTION_PREFIX))
            continue
        if text.startswith(_RESUME_SUMMARY_PREFIX):
            generated_resume = True
            if _AFTER_INTERRUPTION_MARKER not in text:
                return _NormalizedInterruptionState(None, generated_resume=True)
            text = _strip_generated_suffixes(text.split(_AFTER_INTERRUPTION_MARKER, 1)[1])
            continue
        return _NormalizedInterruptionState(text, generated_resume=generated_resume)
    return _NormalizedInterruptionState(text, generated_resume=True)


def _continuity_summary(
    *,
    mode: str,
    episode: Episode,
    origin_episode_id: str,
    inherited_interruption_state: str | None,
) -> str:
    if mode == "foreground":
        summary = "continue the active episode directly from durable state"
    elif mode == "resumed":
        summary = f"resume durable work from episode {origin_episode_id}"
    elif mode == "interrupted":
        summary = f"recover after interruption: {inherited_interruption_state}"
    else:
        summary = (
            f"resume durable work from episode {origin_episode_id} after interruption: {inherited_interruption_state}"
        )
    if episode.parent_episode_id and episode.parent_episode_id != origin_episode_id:
        summary += f"; immediate parent={episode.parent_episode_id}"
    return summary
