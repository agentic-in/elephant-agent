"""Deterministic extraction of tool-trajectory optimization signals."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha1
import logging
import re
from typing import Any

from .types import ToolTrajectorySignal

_TOOL_NAME_RE = re.compile(r"tool\.[a-z0-9_.-]+", re.IGNORECASE)
LOGGER = logging.getLogger(__name__)


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


def _normalized_token(value: object) -> str:
    cleaned = "".join(ch if str(ch).isalnum() else "_" for ch in _text(value).lower())
    return "_".join(part for part in cleaned.split("_") if part)


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
        LOGGER.debug("Failed to parse step sequence for trajectory ordering; using zero.", exc_info=True)
        sequence = 0
    return (sequence, _text(getattr(step, "created_at", "")))


def _confidence(base: float, occurrence_count: int, *, max_bonus: float = 0.4) -> float:
    bonus = min(max_bonus, max(0, occurrence_count - 1) * 0.05)
    return round(min(0.99, base + bonus), 2)


def _load_active_affinity_map(repository: Any, *, personal_model_id: str) -> dict[str, tuple[str, str]]:
    list_facts = getattr(repository, "list_personal_model_facts", None)
    if not callable(list_facts):
        return {}
    try:
        facts = tuple(list_facts(personal_model_id=personal_model_id, status="active"))
    except Exception:
        LOGGER.debug("Failed to load active skill affinity facts for trajectory signals.", exc_info=True)
        return {}
    affinity_map: dict[str, tuple[str, str]] = {}
    for fact in facts:
        metadata = dict(getattr(fact, "metadata", {}) or {})
        topic = _text(metadata.get("topic"))
        if not topic.startswith("world.skills.affinity.") and not topic.startswith("skills.affinity."):
            continue
        skill_id = _text(metadata.get("skill_id"))
        index_id = _text(metadata.get("index_id")) or topic.rsplit(".", 1)[-1]
        if not skill_id and not index_id:
            continue
        for key in {skill_id, index_id, _normalized_token(skill_id), _normalized_token(index_id)} - {""}:
            affinity_map[key] = (skill_id or index_id, index_id or _normalized_token(skill_id))
    return affinity_map


def _extract_instruction_tool_names(skill: Any) -> tuple[str, ...]:
    instruction_text = _text(getattr(skill, "instruction_text", ""))
    if not instruction_text:
        return ()
    return tuple(dict.fromkeys(match.group(0).lower() for match in _TOOL_NAME_RE.finditer(instruction_text)))


def _contains_contiguous_sequence(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    if not haystack or not needle or len(needle) > len(haystack):
        return False
    window = len(needle)
    for index in range(0, len(haystack) - window + 1):
        if tuple(haystack[index : index + window]) == tuple(needle):
            return True
    return False


def load_recent_closed_episodes(
    repository: Any,
    *,
    personal_model_id: str,
    lookback_episodes: int = 30,
) -> tuple[Any, ...]:
    """Load the latest closed episodes for a personal model.

    RuntimeStorageRepository can filter and limit this query in SQLite. Older
    repository-like test doubles may only expose list_episodes() with no
    filters, so this helper keeps a bounded in-memory fallback.
    """

    list_episodes = getattr(repository, "list_episodes", None)
    if not callable(list_episodes):
        return ()
    resolved_limit = max(0, lookback_episodes)
    if resolved_limit == 0:
        return ()
    try:
        episodes = tuple(
            list_episodes(
                personal_model_id=personal_model_id,
                status="closed",
                limit=resolved_limit,
                newest_first=True,
            )
        )
    except TypeError:
        pass
    except Exception:
        LOGGER.debug("Failed to load recent closed episodes with bounded trajectory query.", exc_info=True)
        return ()
    else:
        return episodes
    try:
        episodes = tuple(list_episodes())
    except Exception:
        LOGGER.debug("Failed to load recent closed episodes with compatibility trajectory query.", exc_info=True)
        return ()
    filtered = [
        episode
        for episode in episodes
        if _text(getattr(episode, "personal_model_id", "")) == personal_model_id
        and _text(getattr(episode, "status", "")).lower() == "closed"
    ]
    filtered.sort(key=_started_at_key, reverse=True)
    return tuple(filtered[:resolved_limit])


def _tool_events_for_episode(repository: Any, *, episode_id: str) -> tuple[_ToolEvent, ...]:
    list_loops = getattr(repository, "list_loops", None)
    list_steps = getattr(repository, "list_steps", None)
    if not callable(list_loops) or not callable(list_steps):
        return ()
    try:
        loops = tuple(list_loops(episode_id=episode_id))
    except Exception:
        LOGGER.debug("Failed to load loops while extracting trajectory tool events.", exc_info=True)
        return ()
    if not loops:
        return ()
    episode_steps_by_loop: dict[str, tuple[Any, ...]] | None = None
    try:
        episode_steps = tuple(list_steps(episode_id=episode_id))
    except TypeError:
        episode_steps_by_loop = None
    except Exception:
        LOGGER.debug("Failed to load episode-scoped steps while extracting trajectory tool events.", exc_info=True)
        return ()
    else:
        grouped_steps: dict[str, list[Any]] = defaultdict(list)
        for step in episode_steps:
            grouped_steps[_text(getattr(step, "loop_id", ""))].append(step)
        episode_steps_by_loop = {
            loop_id: tuple(sorted(items, key=_step_sort_key))
            for loop_id, items in grouped_steps.items()
        }
    events: list[_ToolEvent] = []
    for loop in sorted(loops, key=_started_at_key):
        loop_id = _text(getattr(loop, "loop_id", ""))
        try:
            steps = (
                episode_steps_by_loop.get(loop_id, ())
                if episode_steps_by_loop is not None
                else tuple(list_steps(loop_id=loop_id))
            )
        except Exception:
            LOGGER.debug("Failed to load loop-scoped steps while extracting trajectory tool events.", exc_info=True)
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
                LOGGER.debug("Failed to parse tool event sequence while extracting trajectory signals.", exc_info=True)
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


def detect_skill_gaps(
    repository: Any,
    *,
    personal_model_id: str,
    recurring_sequences: Sequence[ToolTrajectorySignal],
    skills: Sequence[Any],
    min_occurrences: int = 3,
) -> tuple[ToolTrajectorySignal, ...]:
    """Detect active skill affinities whose authored procedures lag actual usage."""

    if not recurring_sequences or not skills:
        return ()
    affinity_map = _load_active_affinity_map(repository, personal_model_id=personal_model_id)
    signals: list[ToolTrajectorySignal] = []
    for skill in skills:
        skill_id = _text(getattr(skill, "skill_id", ""))
        display_name = _text(getattr(skill, "display_name", ""))
        affinity = (
            affinity_map.get(skill_id)
            or affinity_map.get(_normalized_token(skill_id))
            or affinity_map.get(_normalized_token(display_name))
        )
        if affinity is None:
            continue
        target_skill_id, target_index_id = affinity
        instruction_tools = _extract_instruction_tool_names(skill)
        best_signal: ToolTrajectorySignal | None = None
        for sequence_signal in recurring_sequences:
            if sequence_signal.occurrence_count < min_occurrences:
                continue
            overlap = len(set(instruction_tools) & set(sequence_signal.tool_names))
            if instruction_tools and overlap > 0:
                continue
            if best_signal is None or (sequence_signal.occurrence_count, sequence_signal.confidence, sequence_signal.signal_id) > (
                best_signal.occurrence_count,
                best_signal.confidence,
                best_signal.signal_id,
            ):
                best_signal = sequence_signal
        if best_signal is None:
            continue
        reason = (
            "authored skill does not encode any tool procedure yet"
            if not instruction_tools
            else "observed workflow bypasses the authored skill procedure"
        )
        signals.append(
            ToolTrajectorySignal(
                signal_id=_stable_id("sig", "skill_gap", target_skill_id, best_signal.tool_names),
                signal_type="skill_gap",
                tool_names=best_signal.tool_names,
                episode_ids=best_signal.episode_ids,
                occurrence_count=best_signal.occurrence_count,
                confidence=_confidence(0.58, best_signal.occurrence_count),
                summary=(
                    f"{target_skill_id} has active affinity, but {' -> '.join(best_signal.tool_names)} recurred in "
                    f"{best_signal.occurrence_count} closed episodes without a matching authored procedure"
                ),
                metadata={
                    "skill_id": target_skill_id,
                    "index_id": target_index_id,
                    "target_scope": target_index_id,
                    "gap_reason": reason,
                    "authored_tools": ",".join(instruction_tools),
                },
            )
        )
    return tuple(sorted(signals, key=lambda item: (-item.confidence, -item.occurrence_count, item.signal_id)))


def detect_outdated_patterns(
    repository: Any,
    *,
    personal_model_id: str,
    recurring_sequences: Sequence[ToolTrajectorySignal],
    skills: Sequence[Any],
    min_occurrences: int = 3,
) -> tuple[ToolTrajectorySignal, ...]:
    """Detect skills whose authored tool sequence has drifted from observed usage."""

    if not recurring_sequences or not skills:
        return ()
    affinity_map = _load_active_affinity_map(repository, personal_model_id=personal_model_id)
    signals: list[ToolTrajectorySignal] = []
    for skill in skills:
        skill_id = _text(getattr(skill, "skill_id", ""))
        if not skill_id:
            continue
        display_name = _text(getattr(skill, "display_name", ""))
        instruction_tools = _extract_instruction_tool_names(skill)
        if len(instruction_tools) < 2:
            continue
        affinity = (
            affinity_map.get(skill_id)
            or affinity_map.get(_normalized_token(skill_id))
            or affinity_map.get(_normalized_token(display_name))
        )
        target_skill_id = affinity[0] if affinity is not None else skill_id
        target_index_id = affinity[1] if affinity is not None else _normalized_token(skill_id)
        best_signal: ToolTrajectorySignal | None = None
        best_score: tuple[int, int, float, str] | None = None
        for sequence_signal in recurring_sequences:
            if sequence_signal.occurrence_count < min_occurrences:
                continue
            overlap = len(set(instruction_tools) & set(sequence_signal.tool_names))
            if overlap <= 0:
                continue
            if _contains_contiguous_sequence(instruction_tools, sequence_signal.tool_names):
                continue
            score = (overlap, sequence_signal.occurrence_count, sequence_signal.confidence, sequence_signal.signal_id)
            if best_score is None or score > best_score:
                best_score = score
                best_signal = sequence_signal
        if best_signal is None:
            continue
        authored_path = " -> ".join(instruction_tools[: max(2, min(3, len(instruction_tools)))])
        observed_path = " -> ".join(best_signal.tool_names)
        signals.append(
            ToolTrajectorySignal(
                signal_id=_stable_id("sig", "outdated_pattern", target_skill_id, best_signal.tool_names),
                signal_type="outdated_pattern",
                tool_names=best_signal.tool_names,
                episode_ids=best_signal.episode_ids,
                occurrence_count=best_signal.occurrence_count,
                confidence=_confidence(0.62, best_signal.occurrence_count),
                summary=(
                    f"{target_skill_id} currently references {authored_path}, but recent closed episodes repeatedly used "
                    f"{observed_path} instead ({best_signal.occurrence_count} episodes)"
                ),
                metadata={
                    "skill_id": target_skill_id,
                    "index_id": target_index_id,
                    "target_scope": target_index_id,
                    "authored_tools": ",".join(instruction_tools),
                    "observed_tools": ",".join(best_signal.tool_names),
                },
            )
        )
    return tuple(sorted(signals, key=lambda item: (-item.confidence, -item.occurrence_count, item.signal_id)))


def extract_trajectory_signals(
    repository: Any,
    *,
    personal_model_id: str,
    lookback_episodes: int = 30,
    min_occurrences: int = 3,
    skills: Sequence[Any] = (),
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
    recurring_sequences = detect_recurring_sequences(episode_sequences, min_occurrences=min_occurrences)
    signals = [
        *recurring_sequences,
        *detect_error_recoveries(repository, episodes=episodes, min_occurrences=max(2, min_occurrences - 1)),
        *detect_tool_combinations(episode_sequences, min_occurrences=max(5, min_occurrences + 2)),
        *detect_skill_gaps(
            repository,
            personal_model_id=personal_model_id,
            recurring_sequences=recurring_sequences,
            skills=skills,
            min_occurrences=min_occurrences,
        ),
        *detect_outdated_patterns(
            repository,
            personal_model_id=personal_model_id,
            recurring_sequences=recurring_sequences,
            skills=skills,
            min_occurrences=min_occurrences,
        ),
    ]
    deduped = {signal.signal_id: signal for signal in signals}
    return tuple(sorted(deduped.values(), key=lambda item: (-item.confidence, -item.occurrence_count, item.signal_id)))
