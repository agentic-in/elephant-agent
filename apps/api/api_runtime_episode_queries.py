"""Bounded Episode queries for API dashboard projections."""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def repository_episodes(
    repository: Any,
    *,
    state_id: str | None = None,
    personal_model_id: str | None = None,
    elephant_id: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    newest_first: bool = False,
) -> tuple[Any, ...]:
    kwargs: dict[str, Any] = {"newest_first": newest_first}
    if state_id is not None:
        kwargs["state_id"] = state_id
    if personal_model_id is not None:
        kwargs["personal_model_id"] = personal_model_id
    if elephant_id is not None:
        kwargs["elephant_id"] = elephant_id
    if status is not None:
        kwargs["status"] = status
    if limit is not None:
        kwargs["limit"] = max(0, int(limit))
    try:
        return tuple(repository.list_episodes(**kwargs))
    except TypeError:
        try:
            episodes = (
                tuple(repository.list_episodes(state_id=state_id))
                if state_id is not None
                else tuple(repository.list_episodes())
            )
        except Exception:
            LOGGER.debug("Fallback repository episode query failed.", exc_info=True)
            return ()
    except Exception:
        LOGGER.debug("Repository episode query failed.", exc_info=True)
        return ()
    if personal_model_id is not None:
        episodes = tuple(
            episode
            for episode in episodes
            if getattr(episode, "personal_model_id", None) == personal_model_id
        )
    if elephant_id is not None:
        episodes = tuple(
            episode
            for episode in episodes
            if getattr(episode, "elephant_id", None) == elephant_id
        )
    if status is not None:
        episodes = tuple(
            episode
            for episode in episodes
            if str(getattr(episode, "status", "")).lower() == status.lower()
        )
    if newest_first:
        episodes = tuple(
            sorted(
                episodes,
                key=lambda episode: (
                    str(getattr(episode, "started_at", "") or ""),
                    str(getattr(episode, "episode_id", "") or ""),
                ),
                reverse=True,
            )
        )
    if limit is not None:
        episodes = episodes[:max(0, int(limit))]
    return episodes
