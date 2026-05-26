from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from packages.reflect.trajectory_signals import (
    _step_sort_key,
    detect_error_recoveries,
    detect_recurring_sequences,
    extract_tool_sequences,
    extract_trajectory_signals,
    load_recent_closed_episodes,
)


class _Repository:
    def __init__(self, *, episodes, loops, steps, facts=()) -> None:
        self._episodes = tuple(episodes)
        self._loops = tuple(loops)
        self._steps = tuple(steps)
        self._facts = tuple(facts)

    def list_episodes(self):
        return self._episodes

    def list_loops(self, *, episode_id=None):
        if episode_id is None:
            return self._loops
        return tuple(loop for loop in self._loops if loop.episode_id == episode_id)

    def list_steps(self, *, loop_id=None):
        if loop_id is None:
            return self._steps
        return tuple(step for step in self._steps if step.loop_id == loop_id)

    def list_personal_model_facts(self, **_: object):
        return self._facts


class _FilteringRepository:
    def __init__(self, episodes) -> None:
        self._episodes = tuple(episodes)
        self.list_episodes_kwargs = None

    def list_episodes(self, **kwargs):
        self.list_episodes_kwargs = dict(kwargs)
        personal_model_id = kwargs.get("personal_model_id")
        status = kwargs.get("status")
        limit = kwargs.get("limit")
        episodes = [
            episode
            for episode in self._episodes
            if episode.personal_model_id == personal_model_id and episode.status == status
        ]
        episodes.sort(
            key=lambda item: (item.started_at, item.episode_id),
            reverse=bool(kwargs.get("newest_first")),
        )
        return tuple(episodes[:limit])


class _EpisodeScopedStepRepository:
    def __init__(self, *, episodes, loops, steps) -> None:
        self._episodes = tuple(episodes)
        self._loops = tuple(loops)
        self._steps = tuple(steps)
        self.step_calls: list[dict[str, object]] = []

    def list_episodes(self, **kwargs):
        episodes = [
            episode
            for episode in self._episodes
            if episode.personal_model_id == kwargs.get("personal_model_id")
            and episode.status == kwargs.get("status")
        ]
        episodes.sort(key=lambda item: item.started_at, reverse=bool(kwargs.get("newest_first")))
        limit = kwargs.get("limit")
        return tuple(episodes[:limit] if limit is not None else episodes)

    def list_loops(self, *, episode_id=None):
        return tuple(loop for loop in self._loops if loop.episode_id == episode_id)

    def list_steps(self, **kwargs):
        self.step_calls.append(dict(kwargs))
        if "loop_id" in kwargs:
            raise AssertionError(f"unexpected per-loop step query: {kwargs!r}")
        episode_id = kwargs.get("episode_id")
        return tuple(step for step in self._steps if step.episode_id == episode_id)

    def list_personal_model_facts(self, **_: object):
        return ()


class TrajectorySignalsTest(unittest.TestCase):
    def setUp(self) -> None:
        now = datetime(2026, 5, 19, tzinfo=timezone.utc)
        self.episodes = (
            SimpleNamespace(episode_id="ep-old", personal_model_id="pm", status="closed", started_at=now - timedelta(days=3)),
            SimpleNamespace(episode_id="ep-mid", personal_model_id="pm", status="closed", started_at=now - timedelta(days=2)),
            SimpleNamespace(episode_id="ep-new", personal_model_id="pm", status="closed", started_at=now - timedelta(days=1)),
            SimpleNamespace(episode_id="ep-open", personal_model_id="pm", status="open", started_at=now),
            SimpleNamespace(episode_id="ep-other", personal_model_id="other", status="closed", started_at=now),
        )
        self.loops = (
            SimpleNamespace(loop_id="loop-old", episode_id="ep-old", started_at=now - timedelta(days=3)),
            SimpleNamespace(loop_id="loop-mid", episode_id="ep-mid", started_at=now - timedelta(days=2)),
            SimpleNamespace(loop_id="loop-new", episode_id="ep-new", started_at=now - timedelta(days=1)),
            SimpleNamespace(loop_id="loop-open", episode_id="ep-open", started_at=now),
        )
        self.steps = (
            SimpleNamespace(loop_id="loop-old", action="call_tool", status="completed", sequence=1, created_at=now, metadata={"tool_name": "tool.terminal.exec"}),
            SimpleNamespace(loop_id="loop-old", action="call_tool", status="completed", sequence=2, created_at=now, metadata={"tool_name": "tool.file.read"}),
            SimpleNamespace(loop_id="loop-mid", action="call_tool", status="failed", sequence=1, created_at=now, metadata={"tool_name": "tool.terminal.exec"}),
            SimpleNamespace(loop_id="loop-mid", action="call_tool", status="completed", sequence=2, created_at=now, metadata={"tool_name": "tool.file.read"}),
            SimpleNamespace(loop_id="loop-new", action="call_tool", status="completed", sequence=1, created_at=now, metadata={"tool_name": "tool.terminal.exec"}),
            SimpleNamespace(loop_id="loop-new", action="call_tool", status="completed", sequence=2, created_at=now, metadata={"tool_name": "tool.file.read"}),
            SimpleNamespace(loop_id="loop-open", action="call_tool", status="completed", sequence=1, created_at=now, metadata={"tool_name": "tool.web.search"}),
        )
        self.repository = _Repository(
            episodes=self.episodes,
            loops=self.loops,
            steps=self.steps,
            facts=(
                SimpleNamespace(
                    metadata={
                        "topic": "world.skills.affinity.workflow_gap",
                        "skill_id": "workflow-gap",
                        "index_id": "workflow_gap",
                    }
                ),
            ),
        )

    def test_load_recent_closed_episodes_filters_by_personal_model_and_status(self) -> None:
        episodes = load_recent_closed_episodes(self.repository, personal_model_id="pm", lookback_episodes=2)

        self.assertEqual(tuple(episode.episode_id for episode in episodes), ("ep-new", "ep-mid"))

    def test_load_recent_closed_episodes_ignores_learning_agent_children(self) -> None:
        now = datetime(2026, 5, 19, tzinfo=timezone.utc)
        repository = _FilteringRepository(
            (
                SimpleNamespace(
                    episode_id="ep-learning",
                    personal_model_id="pm",
                    status="closed",
                    started_at=now,
                    entry_surface="api:sub_agent",
                    metadata={"learning_agent": "true"},
                ),
                SimpleNamespace(
                    episode_id="ep-user",
                    personal_model_id="pm",
                    status="closed",
                    started_at=now - timedelta(minutes=1),
                    entry_surface="api",
                    metadata={},
                ),
            )
        )

        episodes = load_recent_closed_episodes(repository, personal_model_id="pm", lookback_episodes=5)

        self.assertEqual(tuple(episode.episode_id for episode in episodes), ("ep-user",))

    def test_load_recent_closed_episodes_uses_repository_filters_when_available(self) -> None:
        repository = _FilteringRepository(self.episodes)

        episodes = load_recent_closed_episodes(repository, personal_model_id="pm", lookback_episodes=2)

        self.assertEqual(tuple(episode.episode_id for episode in episodes), ("ep-new", "ep-mid"))
        self.assertEqual(
            repository.list_episodes_kwargs,
            {
                "personal_model_id": "pm",
                "status": "closed",
                "limit": 2,
                "newest_first": True,
            },
        )

    def test_extract_tool_sequences_preserves_order(self) -> None:
        episodes = load_recent_closed_episodes(self.repository, personal_model_id="pm", lookback_episodes=3)

        sequences = extract_tool_sequences(self.repository, episodes=episodes)

        self.assertEqual(sequences["ep-old"], ("tool.terminal.exec", "tool.file.read"))
        self.assertEqual(sequences["ep-mid"], ("tool.terminal.exec", "tool.file.read"))

    def test_extract_tool_sequences_uses_episode_scoped_step_query_when_available(self) -> None:
        now = datetime(2026, 5, 19, tzinfo=timezone.utc)
        episodes = (SimpleNamespace(episode_id="ep-new", personal_model_id="pm", status="closed", started_at=now),)
        loops = (
            SimpleNamespace(loop_id="loop-1", episode_id="ep-new", started_at=now),
            SimpleNamespace(loop_id="loop-2", episode_id="ep-new", started_at=now + timedelta(minutes=1)),
        )
        steps = (
            SimpleNamespace(episode_id="ep-new", loop_id="loop-2", action="call_tool", status="completed", sequence=1, created_at=now, metadata={"tool_name": "tool.file.read"}),
            SimpleNamespace(episode_id="ep-new", loop_id="loop-1", action="call_tool", status="completed", sequence=1, created_at=now, metadata={"tool_name": "tool.terminal.exec"}),
        )
        repository = _EpisodeScopedStepRepository(episodes=episodes, loops=loops, steps=steps)

        sequences = extract_tool_sequences(repository, episodes=episodes)

        self.assertEqual(sequences["ep-new"], ("tool.terminal.exec", "tool.file.read"))
        self.assertEqual(repository.step_calls, [{"episode_id": "ep-new"}])

    def test_detect_recurring_sequences_counts_cross_episode_occurrence(self) -> None:
        sequences = {
            "ep-1": ("tool.terminal.exec", "tool.file.read", "tool.terminal.exec"),
            "ep-2": ("tool.terminal.exec", "tool.file.read"),
            "ep-3": ("tool.terminal.exec", "tool.file.read", "tool.web.search"),
        }

        signals = detect_recurring_sequences(sequences, min_occurrences=3)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_type, "recurring_sequence")
        self.assertEqual(signals[0].tool_names, ("tool.terminal.exec", "tool.file.read"))
        self.assertEqual(signals[0].occurrence_count, 3)

    def test_detect_error_recoveries_emits_failed_then_follow_up_pairs(self) -> None:
        episodes = load_recent_closed_episodes(self.repository, personal_model_id="pm", lookback_episodes=3)

        signals = detect_error_recoveries(self.repository, episodes=episodes, min_occurrences=1)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_type, "error_recovery")
        self.assertEqual(signals[0].tool_names, ("tool.terminal.exec", "tool.file.read"))

    def test_extract_trajectory_signals_returns_empty_tuple_for_empty_history(self) -> None:
        repository = _Repository(episodes=(), loops=(), steps=())

        signals = extract_trajectory_signals(repository, personal_model_id="pm")

        self.assertEqual(signals, ())

    def test_episode_load_failures_are_logged(self) -> None:
        class Repository:
            def list_episodes(self, **_: object):
                raise RuntimeError("episode store unavailable")

        with self.assertLogs("packages.reflect.trajectory_signals", level="DEBUG") as logs:
            episodes = load_recent_closed_episodes(Repository(), personal_model_id="pm")

        self.assertEqual(episodes, ())
        self.assertIn("Failed to load recent closed episodes with bounded trajectory query", "\n".join(logs.output))

    def test_compat_episode_load_failures_are_logged(self) -> None:
        class Repository:
            def list_episodes(self, **kwargs):
                if kwargs:
                    raise TypeError("old repository signature")
                raise RuntimeError("episode store unavailable")

        with self.assertLogs("packages.reflect.trajectory_signals", level="DEBUG") as logs:
            episodes = load_recent_closed_episodes(Repository(), personal_model_id="pm")

        self.assertEqual(episodes, ())
        self.assertIn("Failed to load recent closed episodes with compatibility trajectory query", "\n".join(logs.output))

    def test_step_sequence_parse_failure_is_logged(self) -> None:
        class BadStep:
            created_at = "now"

            @property
            def sequence(self):
                raise RuntimeError("bad sequence")

        with self.assertLogs("packages.reflect.trajectory_signals", level="DEBUG") as logs:
            self.assertEqual(_step_sort_key(BadStep()), (0, "now"))

        self.assertIn("Failed to parse step sequence for trajectory ordering", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
