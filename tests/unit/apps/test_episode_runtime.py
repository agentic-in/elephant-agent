from __future__ import annotations

import unittest

from apps.episode_runtime import EpisodeLifecycleService
from packages.contracts.layers import State
from packages.contracts.runtime import PersonalModelRuntimeState


class _ScopedStateRepository:
    def __init__(self) -> None:
        self.state = State(
            state_id="state:elephant-alpha",
            personal_model_id="you",
            state_anchor="elephant:elephant-alpha",
            elephant_id="elephant-alpha",
            elephant_name="Alpha",
        )
        self.list_states_calls: list[dict[str, object]] = []
        self.created_state = False
        self.persisted_episode = None

    def list_states(self, **kwargs: object) -> tuple[State, ...]:
        self.list_states_calls.append(dict(kwargs))
        if kwargs != {"elephant_id": "elephant-alpha", "status": "active"}:
            raise AssertionError(f"unexpected broad state query: {kwargs!r}")
        return (self.state,)

    def create_state(self, **_: object) -> State:
        self.created_state = True
        raise AssertionError("existing elephant state should be resolved, not recreated")

    def upsert_personal_model_runtime_state(self, *_: object, **__: object) -> None:
        return None

    def upsert_episode(self, episode: object) -> None:
        self.persisted_episode = episode


class EpisodeLifecycleServiceTest(unittest.TestCase):
    def test_start_episode_resolves_existing_elephant_state_with_scoped_query(self) -> None:
        repository = _ScopedStateRepository()
        service = EpisodeLifecycleService(repository)  # type: ignore[arg-type]

        episode = service.start_episode(
            PersonalModelRuntimeState(profile_id="you", display_name="You", mode="companion"),
            elephant_id="elephant-alpha",
            episode_id="episode-alpha",
        )

        self.assertEqual(episode.state_id, "state:elephant-alpha")
        self.assertEqual(episode.elephant_id, "elephant-alpha")
        self.assertFalse(repository.created_state)
        self.assertEqual(
            repository.list_states_calls,
            [{"elephant_id": "elephant-alpha", "status": "active"}],
        )
        self.assertIs(repository.persisted_episode, episode)


if __name__ == "__main__":
    unittest.main()
