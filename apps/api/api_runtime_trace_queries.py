"""Bounded runtime trace query helpers for API dashboard projections."""

from __future__ import annotations

from typing import Any


def trace_episode_id(value: Any) -> str:
    return str(getattr(value, "episode_id", "") or "").strip()


def trace_loop_id(value: Any) -> str:
    return str(getattr(value, "loop_id", "") or "").strip()


def loops_for_episodes(repository: Any, episodes: tuple[Any, ...]) -> tuple[Any, ...]:
    loop_rows: list[Any] = []
    for episode in episodes:
        episode_id = trace_episode_id(episode)
        if not episode_id:
            continue
        loop_rows.extend(repository.list_loops(episode_id=episode_id))
    return tuple(loop_rows)


def steps_by_loop_for_episodes(
    repository: Any,
    *,
    episodes: tuple[Any, ...],
    loops: tuple[Any, ...],
) -> dict[str, tuple[Any, ...]]:
    loop_ids = tuple(trace_loop_id(loop) for loop in loops if trace_loop_id(loop))
    if not loop_ids:
        return {}
    try:
        grouped_steps: dict[str, list[Any]] = {loop_id: [] for loop_id in loop_ids}
        for episode in episodes:
            episode_id = trace_episode_id(episode)
            if not episode_id:
                continue
            for step in repository.list_steps(episode_id=episode_id):
                step_loop_id = trace_loop_id(step)
                if step_loop_id in grouped_steps:
                    grouped_steps[step_loop_id].append(step)
    except TypeError:
        return {loop_id: tuple(repository.list_steps(loop_id=loop_id)) for loop_id in loop_ids}
    return {loop_id: tuple(grouped_steps.get(loop_id, ())) for loop_id in loop_ids}


__all__ = [
    "loops_for_episodes",
    "steps_by_loop_for_episodes",
    "trace_episode_id",
    "trace_loop_id",
]
