"""Deterministic extraction of tool-trajectory optimization signals."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha1
from typing import Any

from .types import ToolTrajectorySignal


@dataclass(frozen=True, slots=True)
class _ToolEvent:
    episode_id: str
    tool_name: str
    status: str
    sequence: int


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return f"{prefix}_{sha1(payload.encode('utf-8')).hexdigest()[:12]}"


def _text(value: object) -> str:
    return str(value or "").strip()


def _metadata(step: Any) -> Mapping[str, Any]:
    raw = getattr(step, "metadata", {})
    if isinstance(raw, Mapping):
        return raw
    return {}


def _started_at_key(item: Any) -> tuple[str, str]:
    return (_text(getattr(item, "started_at", "")), _text(getattr(item, "episode_id", getattr(item, "loop_id", ""))))


def _step_sort_key(step: Any) -> tuple[int, str]:
    try:
        sequence = int(getattr(step, "sequence", 0) or 0)
    except Exception:
        sequence = 0
    return (sequence, _text(getattr(step, "created_at", "")))


def _confidence(base: float, occurrence_count: int, *, max_bonus: float = 0.4) -> float:
    bonus = min(max_bonus, max(0, occurrence_count - 1) * 0.05)
    return round(min(0.99, base + bonus), 2)


def load_recent_closed_episodes(
    repository: Any,
    *,
    personal_model_id: str,
    lookback_episodes: int = 30,
) -> tuple[Any, ...]:
    """Load the latest closed episodes for a personal model.

    Repository currently exposes list_episodes() without filters for
    personal_model_id, status, or limit. This helper applies those filters in
    memory and returns the newest episodes first.
    """

    list_episodes = getattr(repository, "list_episodes", None)
    if not callable(list_episodes):
        return ()
    try:
        episodes = tuple(list_episodes())
    except Exception:
        return ()
    filtered = [
        episode
        for episode in episodes
        if _text(getattr(episode, "personal_model_id", "")) == personal_model_id
        and _text(getattr(episode, "status", "")).lower() == "closed"
    ]
    filtered.sort(key=_started_at_key, reverse=True)
    return tuple(filtered[: max(0, lookback_episodes)])


def _tool_events_for_episode(repository: Any, *, episode_id: str) -> tuple[_ToolEvent, ...]:
    list_loops = getattr(repository, "list_loops", None)
    list_steps = getattr(repository, "list_steps", None)
    if not callable(list_loops) or not callable(list_steps):
        return ()
    try:
        loops = tuple(list_loops(episode_id=episode_id))
    except Exception:
        return ()
    if not loops:
        return ()
    events: list[_ToolEvent] = []
    for loop in sorted(loops, key=_started_at_key):
        try:
            steps = tuple(list_steps(loop_id=_text(getattr(loop, "loop_id", ""))))
        except Exception:
            continue
        for step in sorted(steps, key=_step_sort_key):
            if _text(getattr(step, "action", "")) != "call_tool":
                continue
            metadata = _metadata(step)
            tool_name = _text(metadata.get("tool_name"))
            if not tool_name:
                continue
            try:
                sequence = int(getattr(step, "sequence", 0) or 0)
            except Exception:
                sequence = 0
            events.append(
                _ToolEvent(
                    episode_id=episode_id,
                    tool_name=tool_name,
                    status=_text(getattr(step, "status", "")) or "completed",
                    sequence=sequence,
                )
            )
    return tuple(sorted(events, key=lambda item: item.sequence))


def extract_tool_sequences(
    repository: Any,
    *,
    episodes: Sequence[Any],
) -> dict[str, tuple[str, ...]]:
    """Extract ordered tool sequences from a set of episodes."""

    sequences: dict[str, tuple[str, ...]] = {}
    for episode in episodes:
        episode_id = _text(getattr(episode, "episode_id", ""))
        if not episode_id:
            continue
        events = _tool_events_for_episode(repository, episode_id=episode_id)
        sequences[episode_id] = tuple(event.tool_name for event in events)
    return sequences


def detect_recurring_sequences(
    episode_sequences: Mapping[str, Sequence[str]],
    *,
    min_occurrences: int = 3,
    ngram_sizes: Sequence[int] = (2, 3),
) -> tuple[ToolTrajectorySignal, ...]:
    """Detect repeated n-gram tool sequences across episodes."""

    occurrences: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for episode_id, sequence in episode_sequences.items():
        tools = tuple(_text(tool) for tool in sequence if _text(tool))
        if not tools:
            continue
        for ngram_size in ngram_sizes:
            if len(tools) < ngram_size:
                continue
            seen_in_episode: set[tuple[str, ...]] = set()
            for index in range(0, len(tools) - ngram_size + 1):
                ngram = tools[index : index + ngram_size]
                if ngram in seen_in_episode:
                    continue
                seen_in_episode.add(ngram)
                occurrences[ngram].add(episode_id)
    signals: list[ToolTrajectorySignal] = []
    for tool_names, episode_ids in occurrences.items():
        if len(episode_ids) < min_occurrences:
            continue
        occurrence_count = len(episode_ids)
        signals.append(
            ToolTrajectorySignal(
                signal_id=_stable_id("sig", "recurring_sequence", tool_names),
                signal_type="recurring_sequence",
                tool_names=tuple(tool_names),
                episode_ids=tuple(sorted(episode_ids)),
                occurrence_count=occurrence_count,
                confidence=_confidence(0.55 + (len(tool_names) - 2) * 0.05, occurrence_count),
                summary=(
                    f"{' -> '.join(tool_names)} recurred in {occurrence_count} closed episodes"
                ),
                metadata={"ngram_size": str(len(tool_names))},
            )
        )
    return tuple(sorted(signals, key=lambda item: (-item.confidence, -item.occurrence_count, item.signal_id)))


def detect_error_recoveries(
    repository: Any,
    *,
    episodes: Sequence[Any],
    min_occurrences: int = 2,
) -> tuple[ToolTrajectorySignal, ...]:
    """Detect failed tool calls followed by a recovery tool call."""

    recoveries: dict[tuple[str, str], set[str]] = defaultdict(set)
    for episode in episodes:
        episode_id = _text(getattr(episode, "episode_id", ""))
        if not episode_id:
            continue
        events = _tool_events_for_episode(repository, episode_id=episode_id)
        for current_event, next_event in zip(events, events[1:]):
            if current_event.status.lower() != "failed":
                continue
            recoveries[(current_event.tool_name, next_event.tool_name)].add(episode_id)
    signals: list[ToolTrajectorySignal] = []
    for tool_pair, episode_ids in recoveries.items():
        if len(episode_ids) < min_occurrences:
            continue
        occurrence_count = len(episode_ids)
        failed_tool, recovery_tool = tool_pair
        signals.append(
            ToolTrajectorySignal(
                signal_id=_stable_id("sig", "error_recovery", tool_pair),
                signal_type="error_recovery",
                tool_names=tool_pair,
                episode_ids=tuple(sorted(episode_ids)),
                occurrence_count=occurrence_count,
                confidence=_confidence(0.6, occurrence_count),
                summary=(
                    f"{failed_tool} failures were followed by {recovery_tool} in {occurrence_count} closed episodes"
                ),
                metadata={"failed_tool": failed_tool, "recovery_tool": recovery_tool},
            )
        )
    return tuple(sorted(signals, key=lambda item: (-item.confidence, -item.occurrence_count, item.signal_id)))


def detect_tool_combinations(
    episode_sequences: Mapping[str, Sequence[str]],
    *,
    min_occurrences: int = 5,
) -> tuple[ToolTrajectorySignal, ...]:
    """Detect high-frequency co-occurring tool pairs across episodes."""

    combinations: dict[tuple[str, str], set[str]] = defaultdict(set)
    for episode_id, sequence in episode_sequences.items():
        unique_tools = sorted({_text(tool) for tool in sequence if _text(tool)})
        if len(unique_tools) < 2:
            continue
        for index, left in enumerate(unique_tools[:-1]):
            for right in unique_tools[index + 1 :]:
                combinations[(left, right)].add(episode_id)
    signals: list[ToolTrajectorySignal] = []
    for tool_pair, episode_ids in combinations.items():
        if len(episode_ids) < min_occurrences:
            continue
        occurrence_count = len(episode_ids)
        signals.append(
            ToolTrajectorySignal(
                signal_id=_stable_id("sig", "tool_combination", tool_pair),
                signal_type="tool_combination",
                tool_names=tool_pair,
                episode_ids=tuple(sorted(episode_ids)),
                occurrence_count=occurrence_count,
                confidence=_confidence(0.5, occurrence_count),
                summary=(
                    f"{' + '.join(tool_pair)} co-occurred in {occurrence_count} closed episodes"
                ),
                metadata={"combination_size": "2"},
            )
        )
    return tuple(sorted(signals, key=lambda item: (-item.confidence, -item.occurrence_count, item.signal_id)))


def extract_trajectory_signals(
    repository: Any,
    *,
    personal_model_id: str,
    lookback_episodes: int = 30,
    min_occurrences: int = 3,
) -> tuple[ToolTrajectorySignal, ...]:
    """Extract deterministic optimization signals from recent closed episodes."""

    episodes = load_recent_closed_episodes(
        repository,
        personal_model_id=personal_model_id,
        lookback_episodes=lookback_episodes,
    )
    if not episodes:
        return ()
    episode_sequences = extract_tool_sequences(repository, episodes=episodes)
    signals = [
        *detect_recurring_sequences(episode_sequences, min_occurrences=min_occurrences),
        *detect_error_recoveries(repository, episodes=episodes, min_occurrences=max(2, min_occurrences - 1)),
        *detect_tool_combinations(repository_sequences := episode_sequences, min_occurrences=max(5, min_occurrences + 2)),
    ]
    deduped = {signal.signal_id: signal for signal in signals}
    return tuple(sorted(deduped.values(), key=lambda item: (-item.confidence, -item.occurrence_count, item.signal_id)))
