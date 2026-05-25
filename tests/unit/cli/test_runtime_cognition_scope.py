from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from apps.cli.runtime_cognition import _list_scope_recall_evidence


class RuntimeCognitionScopeTests(unittest.TestCase):
    def test_scope_recall_evidence_queries_each_scoped_episode(self) -> None:
        class Repository:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def list_steps(self, **kwargs: object) -> tuple[SimpleNamespace, ...]:
                self.calls.append(dict(kwargs))
                episode_id = str(kwargs.get("episode_id") or "")
                return (
                    SimpleNamespace(
                        step_id=f"step:{episode_id}",
                        episode_id=episode_id,
                        loop_id=f"loop:{episode_id}",
                        action="record_input",
                        summary=f"summary for {episode_id}",
                        outcome="",
                        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        metadata={},
                    ),
                )

        repository = Repository()

        records = _list_scope_recall_evidence(
            repository,  # type: ignore[arg-type]
            scope_session_ids=("episode:1", "episode:2"),
        )

        self.assertEqual(
            repository.calls,
            [{"episode_id": "episode:1"}, {"episode_id": "episode:2"}],
        )
        self.assertEqual(tuple(record.episode_id for record in records), ("episode:1", "episode:2"))


if __name__ == "__main__":
    unittest.main()
