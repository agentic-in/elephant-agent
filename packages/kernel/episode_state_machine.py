"""Unified Episode state machine — single close path with guaranteed side-effects."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from packages.contracts.layers import Episode

from .runtime_support import KernelStoragePort


@dataclass(frozen=True, slots=True)
class EpisodeTransition:
    parent_episode: Episode
    episode: Episode
    lineage: tuple[Episode, ...]


def close_episode(
    storage: KernelStoragePort,
    episode_id: str,
    *,
    reason: str,
    summary: str,
    current: datetime | None = None,
    semantic_summary_indexer: object | None = None,
) -> Episode:
    """Close an episode with guaranteed side-effects (indexing + learning enqueue).

    This is the ONLY path through which an episode should be closed.
    All close entry points (kernel single_turn, shell EOF, /clear, gateway idle)
    must call this function.

    Args:
        storage: The kernel storage port.
        episode_id: The episode to close.
        reason: Close reason — "final_response", "idle_timeout", "shell_exit",
                "shell_clear", "user_requested".
        summary: Exit summary text for future recall.
        current: Timestamp (defaults to now).
        semantic_summary_indexer: Optional semantic indexer for exit summary recall.

    Returns:
        The closed Episode.
    """
    if current is None:
        current = datetime.now(timezone.utc)

    episode = storage.load_episode(episode_id)
    if episode is None:
        raise KeyError(f"episode not found: {episode_id}")
    if episode.status == "closed":
        return episode  # idempotent

    closed = replace(
        episode,
        status="closed",
        ended_at=current,
        updated_at=current,
        exit_summary=summary or episode.exit_summary,
        metadata={**dict(episode.metadata), "closed_reason": reason},
    )
    storage.upsert_episode(closed)

    # Side-effect 1: Index exit summary for future semantic recall
    if semantic_summary_indexer is not None:
        index_exit = getattr(semantic_summary_indexer, "index_episode_exit", None)
        if callable(index_exit):
            try:
                index_exit(closed)
            except Exception:
                pass

    # Side-effect 2: Enqueue learning job
    enqueue = getattr(storage, "enqueue_learning_job", None)
    if callable(enqueue):
        loops = storage.list_loops(episode_id=episode_id)
        loop = loops[-1] if loops else None
        try:
            enqueue(
                job_type="episode_boundary_learning",
                trigger=_trigger_from_reason(reason),
                personal_model_id=closed.personal_model_id,
                state_id=closed.state_id,
                episode_id=closed.episode_id,
                loop_id=loop.loop_id if loop is not None else None,
                summary=closed.exit_summary,
                metadata={"closed_reason": reason, "source": "episode_state_machine"},
            )
        except Exception:
            pass

    return closed


def _continuation_note(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _opening_resume_metadata(
    storage: KernelStoragePort,
    parent: Episode,
    *,
    reason: str,
    current: datetime,
) -> dict[str, str]:
    state = storage.load_state(parent.state_id)
    state_note = _continuation_note(getattr(state, "current_context_note", "")) if state is not None else ""
    summary = _continuation_note(parent.exit_summary)
    note = summary or state_note
    metadata = {
        "transition_reason": reason,
        "parent_episode_id": parent.episode_id,
        "opened_at": current.isoformat(),
    }
    if note:
        metadata["opening_resume_snapshot"] = note
        metadata["opening_resume_source"] = "parent.exit_summary" if summary else "state.current_context_note"
        metadata["opening_resume_state_id"] = parent.state_id
    return metadata


def _lineage(storage: KernelStoragePort, episode_id: str) -> tuple[Episode, ...]:
    lineage: list[Episode] = []
    seen: set[str] = set()
    current = storage.load_episode(episode_id)
    while current is not None and current.episode_id not in seen:
        lineage.append(current)
        seen.add(current.episode_id)
        parent_id = current.parent_episode_id
        if parent_id is None:
            break
        current = storage.load_episode(parent_id)
    return tuple(reversed(lineage))


def open_next_episode(
    storage: KernelStoragePort,
    previous_episode_id: str,
    *,
    reason: str,
    summary: str = "",
    current: datetime | None = None,
    episode_id: str | None = None,
    entry_surface: str | None = None,
    semantic_summary_indexer: object | None = None,
) -> EpisodeTransition:
    """Close the previous Episode if needed and open the next Episode/Session.

    One user-visible session is one Episode. This transition is the canonical
    way to move from an existing Episode to the next conversation window.
    """
    if current is None:
        current = datetime.now(timezone.utc)

    previous = storage.load_episode(previous_episode_id)
    if previous is None:
        raise KeyError(f"episode not found: {previous_episode_id}")

    close_summary = (summary or previous.exit_summary).strip()
    parent = previous
    if previous.status != "closed":
        parent = close_episode(
            storage,
            previous.episode_id,
            reason=reason,
            summary=close_summary,
            current=current,
            semantic_summary_indexer=semantic_summary_indexer,
        )

    state = storage.load_state(parent.state_id)
    next_episode = Episode(
        episode_id=episode_id or uuid4().hex,
        state_id=parent.state_id,
        personal_model_id=parent.personal_model_id,
        entry_surface=entry_surface or parent.entry_surface,
        status="open",
        started_at=current,
        updated_at=current,
        elephant_id=parent.elephant_id or (getattr(state, "elephant_id", "") if state is not None else ""),
        parent_episode_id=parent.episode_id,
        metadata=_opening_resume_metadata(storage, parent, reason=reason, current=current),
    )
    storage.upsert_episode(next_episode)

    record_transition = getattr(storage, "record_episode_transition", None)
    if callable(record_transition):
        record_transition(parent.episode_id, next_episode.episode_id, current, reason=reason)

    refreshed = storage.load_episode(next_episode.episode_id) or next_episode
    return EpisodeTransition(
        parent_episode=storage.load_episode(parent.episode_id) or parent,
        episode=refreshed,
        lineage=_lineage(storage, refreshed.episode_id),
    )


def _trigger_from_reason(reason: str) -> str:
    """Map close reason to learning trigger type."""
    mapping = {
        "shell_exit": "episode_close",
        "shell_clear": "episode_close",
        "final_response": "episode_close",
        "user_requested": "episode_close",
    }
    return mapping.get(reason, "episode_close")
