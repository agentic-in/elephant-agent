from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from apps.cli.runtime_snapshot import _growth_state_predates_profile_sessions


class RuntimeSnapshotGrowthTests(unittest.TestCase):
    def test_growth_staleness_check_uses_bounded_personal_model_episode_query(self) -> None:
        class Repository:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def list_episodes(self, **kwargs: object) -> tuple[SimpleNamespace, ...]:
                self.calls.append(dict(kwargs))
                return (
                    SimpleNamespace(
                        personal_model_id="you",
                        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    ),
                )

        repository = Repository()
        runtime = SimpleNamespace(repository=repository)
        state = SimpleNamespace(
            updated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            created_at=None,
            last_dialogue_at=None,
            first_dialogue_at=None,
        )

        stale = _growth_state_predates_profile_sessions(runtime, profile_id="you", state=state)

        self.assertTrue(stale)
        self.assertEqual(
            repository.calls,
            [{"personal_model_id": "you", "limit": 1, "newest_first": False}],
        )


if __name__ == "__main__":
    unittest.main()
