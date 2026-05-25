from __future__ import annotations

from datetime import datetime, timezone
import unittest

from apps.cli.runtime_records import CliRuntimeRecordsMixin
from packages.contracts.layers import Episode


class RuntimeRecordsTests(unittest.TestCase):
    def test_recent_sessions_uses_bounded_episode_query(self) -> None:
        class Repository:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []
                self.episodes = {
                    "episode:new": _episode("episode:new", "2026-05-02T00:00:00+00:00"),
                    "episode:old": _episode("episode:old", "2026-05-01T00:00:00+00:00"),
                }

            def list_episodes(self, **kwargs: object) -> tuple[Episode, ...]:
                self.calls.append(dict(kwargs))
                return (self.episodes["episode:new"],)

            def load_episode_state(self, episode_id: str) -> Episode | None:
                return self.episodes.get(episode_id)

        class Runtime(CliRuntimeRecordsMixin):
            def __init__(self) -> None:
                self.repository = Repository()

        runtime = Runtime()

        sessions = runtime.recent_sessions(limit=1)

        self.assertEqual(runtime.repository.calls, [{"limit": 1, "newest_first": True}])
        self.assertEqual(tuple(session.episode_id for session in sessions), ("episode:new",))

    def test_latest_session_for_elephant_uses_scoped_episode_queries(self) -> None:
        class Repository:
            def __init__(self) -> None:
                self.episode_calls: list[dict[str, object]] = []
                self.state_calls: list[dict[str, object]] = []
                self.episodes = {
                    "episode:direct": _episode(
                        "episode:direct",
                        "2026-05-02T00:00:00+00:00",
                        elephant_id="atlas",
                        state_id="state:atlas",
                    ),
                    "episode:state": _episode(
                        "episode:state",
                        "2026-05-03T00:00:00+00:00",
                        state_id="state:atlas",
                    ),
                }

            def list_episodes(self, **kwargs: object) -> tuple[Episode, ...]:
                self.episode_calls.append(dict(kwargs))
                if kwargs.get("elephant_id") == "atlas":
                    return (self.episodes["episode:direct"],)
                if kwargs.get("state_id") == "state:atlas":
                    return (self.episodes["episode:state"],)
                return ()

            def list_states(self, **kwargs: object) -> tuple[object, ...]:
                self.state_calls.append(dict(kwargs))
                return (_state("state:atlas", elephant_id="atlas"),)

            def load_state(self, state_id: str) -> object | None:
                return _state(state_id, elephant_id="atlas") if state_id == "state:atlas" else None

            def load_episode_state(self, episode_id: str) -> Episode | None:
                return self.episodes.get(episode_id)

        class Runtime(CliRuntimeRecordsMixin):
            def __init__(self) -> None:
                self.repository = Repository()

        runtime = Runtime()

        session = runtime.latest_session_for_elephant("atlas")

        self.assertEqual(session.episode_id if session is not None else None, "episode:state")
        self.assertEqual(
            runtime.repository.episode_calls,
            [
                {"elephant_id": "atlas", "limit": None, "newest_first": True},
                {"state_id": "state:atlas", "limit": None, "newest_first": True},
            ],
        )
        self.assertEqual(runtime.repository.state_calls, [{"elephant_id": "atlas"}])

    def test_latest_session_for_elephant_skips_hidden_latest_episode(self) -> None:
        class Repository:
            def __init__(self) -> None:
                self.episodes = {
                    "episode:hidden": _episode(
                        "episode:hidden",
                        "2026-05-04T00:00:00+00:00",
                        elephant_id="atlas",
                        state_id="state:atlas",
                        metadata={"episode_kind": "sub_agent"},
                    ),
                    "episode:visible": _episode(
                        "episode:visible",
                        "2026-05-03T00:00:00+00:00",
                        elephant_id="atlas",
                        state_id="state:atlas",
                    ),
                }

            def list_episodes(self, **kwargs: object) -> tuple[Episode, ...]:
                if kwargs.get("elephant_id") == "atlas" or kwargs.get("state_id") == "state:atlas":
                    return (self.episodes["episode:hidden"], self.episodes["episode:visible"])
                return ()

            def list_states(self, **kwargs: object) -> tuple[object, ...]:
                return (_state("state:atlas", elephant_id="atlas"),)

            def load_state(self, state_id: str) -> object | None:
                return _state(state_id, elephant_id="atlas") if state_id == "state:atlas" else None

            def load_episode_state(self, episode_id: str) -> Episode | None:
                return self.episodes.get(episode_id)

        class Runtime(CliRuntimeRecordsMixin):
            def __init__(self) -> None:
                self.repository = Repository()

        runtime = Runtime()

        session = runtime.latest_session_for_elephant("atlas")

        self.assertEqual(session.episode_id if session is not None else None, "episode:visible")

    def test_session_ids_for_elephant_filters_legacy_unscoped_episode_fallback(self) -> None:
        class Repository:
            def __init__(self) -> None:
                self.calls = 0
                self.episodes = {
                    "episode:other": _episode(
                        "episode:other",
                        "2026-05-04T00:00:00+00:00",
                        elephant_id="other",
                        state_id="state:other",
                    ),
                    "episode:target": _episode(
                        "episode:target",
                        "2026-05-03T00:00:00+00:00",
                        state_id="state:atlas",
                    ),
                }

            def list_episodes(self) -> tuple[Episode, ...]:
                self.calls += 1
                return tuple(self.episodes.values())

            def list_states(self) -> tuple[object, ...]:
                return (_state("state:atlas", elephant_id="atlas"),)

            def load_state(self, state_id: str) -> object | None:
                return _state(state_id, elephant_id="atlas") if state_id == "state:atlas" else None

            def load_episode_state(self, episode_id: str) -> Episode | None:
                return self.episodes.get(episode_id)

        class Runtime(CliRuntimeRecordsMixin):
            def __init__(self) -> None:
                self.repository = Repository()

        runtime = Runtime()

        session_ids = runtime.session_ids_for_elephant("atlas")

        self.assertEqual(session_ids, ("episode:target",))
        self.assertGreaterEqual(runtime.repository.calls, 1)


def _episode(
    episode_id: str,
    started_at: str,
    *,
    elephant_id: str = "",
    state_id: str = "state:test",
    metadata: dict[str, str] | None = None,
) -> Episode:
    return Episode(
        episode_id=episode_id,
        state_id=state_id,
        personal_model_id="you",
        entry_surface="cli",
        status="closed",
        started_at=datetime.fromisoformat(started_at).replace(tzinfo=timezone.utc),
        elephant_id=elephant_id,
        metadata=metadata or {},
    )


def _state(state_id: str, *, elephant_id: str) -> object:
    return type(
        "StateStub",
        (),
        {
            "state_id": state_id,
            "elephant_id": elephant_id,
            "state_anchor": f"elephant:{elephant_id}",
        },
    )()


if __name__ == "__main__":
    unittest.main()
