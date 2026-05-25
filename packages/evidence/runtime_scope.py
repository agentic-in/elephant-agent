"""Scope resolution helpers for evidence retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from packages.storage import RuntimeStorageRepository

LOGGER = logging.getLogger(__name__)


def _query_episode_ids(
    repository: RuntimeStorageRepository,
    *,
    personal_model_id: str | None = None,
    elephant_id: str | None = None,
) -> tuple[str, ...]:
    if not personal_model_id and not elephant_id:
        return ()
    episode_rows: list[object] = []

    def list_episodes(**kwargs: object) -> tuple[object, ...]:
        try:
            return tuple(repository.list_episodes(**kwargs))
        except TypeError:
            return tuple(repository.list_episodes())

    if elephant_id:
        kwargs: dict[str, object] = {"elephant_id": elephant_id, "newest_first": True}
        if personal_model_id:
            kwargs["personal_model_id"] = personal_model_id
        episode_rows.extend(list_episodes(**kwargs))
        try:
            states = tuple(
                repository.list_states(
                    personal_model_id=personal_model_id,
                    elephant_id=elephant_id,
                )
            )
        except TypeError:
            states = tuple(
                state
                for state in repository.list_states(personal_model_id=personal_model_id)
                if getattr(state, "elephant_id", "") == elephant_id
            )
        except Exception:
            LOGGER.warning(
                "failed to list states while resolving evidence scope",
                extra={"personal_model_id": personal_model_id, "elephant_id": elephant_id},
                exc_info=True,
            )
            states = ()
        for state in states:
            state_kwargs: dict[str, object] = {
                "state_id": getattr(state, "state_id", ""),
                "newest_first": True,
            }
            if personal_model_id:
                state_kwargs["personal_model_id"] = personal_model_id
            episode_rows.extend(list_episodes(**state_kwargs))
    else:
        kwargs = {"personal_model_id": personal_model_id, "newest_first": True}
        episode_rows.extend(list_episodes(**kwargs))

    episode_ids: list[str] = []
    for episode in sorted(
        episode_rows,
        key=lambda item: (
            item.metadata.get("updated_at", ""),
            (item.ended_at or item.started_at).isoformat(),
            item.episode_id,
        ),
        reverse=True,
    ):
        if personal_model_id and episode.personal_model_id != personal_model_id:
            continue
        if elephant_id:
            episode_elephant_id = getattr(episode, "elephant_id", "")
            if episode_elephant_id:
                if episode_elephant_id != elephant_id:
                    continue
            else:
                state = repository.load_state(episode.state_id)
                if state is None or state.elephant_id != elephant_id:
                    continue
        episode_ids.append(episode.episode_id)
    return tuple(dict.fromkeys(episode_ids))


@dataclass(frozen=True, slots=True)
class _ResolvedScope:
    episode_ids: tuple[str, ...]
    opened_scopes: tuple[str, ...]
    scope_reason: str
    lineage_episode_ids: tuple[str, ...]
    elephant_episode_ids: tuple[str, ...]
    personal_model_episode_ids: tuple[str, ...]
