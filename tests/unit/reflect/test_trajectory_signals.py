from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from packages.reflect.trajectory_signals import (
    detect_error_recoveries,
    detect_recurring_sequences,
    extract_tool_sequences,
    extract_trajectory_signals,
    load_recent_closed_episodes,
)


class _Repository:
    def __init__(self, *, episodes, loops, steps) -> None:
        self._episodes = tuple(episodes)
        self._loops = tuple(loops)
        self._steps = tuple(steps)

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
        self.repository = _Repository(episodes=self.episodes, loops=self.loops, steps=self.steps)

    def test_load_recent_closed_episodes_filters_by_personal_model_and_status(self) -> None:
        episodes = load_recent_closed_episodes(self.repository, personal_model_id="pm", lookback_episodes=2)

        self.assertEqual(tuple(episode.episode_id for episode in episodes), ("ep-new", "ep-mid"))

    def test_extract_tool_sequences_preserves_order(self) -> None:
        episodes = load_recent_closed_episodes(self.repository, personal_model_id="pm", lookback_episodes=3)

        sequences = extract_tool_sequences(self.repository, episodes=episodes)

        self.assertEqual(sequences["ep-old"], ("tool.terminal.exec", "tool.file.read"))
        self.assertEqual(sequences["ep-mid"], ("tool.terminal.exec", "tool.file.read"))

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


if __name__ == "__main__":
    unittest.main()
