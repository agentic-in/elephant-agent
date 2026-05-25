from __future__ import annotations

from datetime import datetime, timezone

from apps.cli.runtime import CliRuntime
from packages.contracts import Fact
from tests.e2e.cli.cli_surface_test_base import CliSurfaceE2ETestBase


class CliSurfaceFactsE2ETest(CliSurfaceE2ETestBase):
    def test_facts_cli_lists_and_deletes_personal_model_facts(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        runtime = CliRuntime.create(state_dir=self.state_dir)
        session = runtime.latest_session_for_elephant("seed")
        self.assertIsNotNone(session)
        assert session is not None
        listed = self._run("facts")
        self.assertIn("Elephant Agent understanding", listed.stdout)
        self.assertIn("facts ·", listed.stdout)
        self.assertIn("status_breakdown", listed.stdout)

        fact_id = "fact:stale-preference"
        runtime.repository.upsert_personal_model_fact(
            Fact(
                fact_id=fact_id,
                personal_model_id=session.personal_model_id,
                lens="identity",
                text="cleanup stale preference",
                confidence=0.7,
                committed_at=datetime.now(timezone.utc),
                source="user_explicit",
                source_episode_ids=(session.episode_id,),
                metadata={"topic": "identity.style.preference.cleanup"},
            )
        )
        populated = self._run("facts")
        self.assertIn(fact_id, populated.stdout)
        self.assertIn("cleanup stale preference", populated.stdout)

        deleted = self._run(
            "facts", "delete", fact_id, "--reason", "cleanup stale preference"
        )
        self.assertIn("cleanup stale preference", deleted.stdout)

        refreshed = CliRuntime.create(state_dir=self.state_dir)
        facts = refreshed.repository.list_personal_model_facts(
            personal_model_id=session.personal_model_id, status=("deleted",)
        )
        entry = next((fact for fact in facts if fact.fact_id == fact_id), None)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.status, "deleted")

        visible = self._run("facts")
        self.assertNotIn(fact_id, visible.stdout)
        self.assertNotIn("status=deleted", visible.stdout)


if __name__ == "__main__":
    import unittest

    unittest.main()
