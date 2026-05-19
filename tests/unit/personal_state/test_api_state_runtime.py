from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from apps.api.state_runtime import APIStateService
from packages.contracts import PersonalModel
from packages.contracts.layers import Episode
from packages.contracts.runtime import PersonalModelRuntimeState
from packages.evidence.recall_runtime import RecallRuntime
from packages.storage import RuntimeStorageRepository


class APIStateServiceTest(unittest.TestCase):
    def _build_runtime(self):
        tmpdir = tempfile.TemporaryDirectory()
        repository = RuntimeStorageRepository(Path(tmpdir.name) / "state" / "elephant.sqlite3")
        repository.bootstrap()
        personal_model = PersonalModelRuntimeState(
            profile_id="personal-model-api",
            display_name="Elephant Agent API Test",
            mode="companion",
        )
        repository.upsert_personal_model(
            PersonalModel(
                personal_model_id="you",
                display_name=personal_model.display_name,
                status="active",
                metadata={"mode": personal_model.mode},
            )
        )
        state = repository.create_state(
            personal_model_id=personal_model.profile_id,
            state_id="state:api-test",
            state_anchor="elephant:elephant-api-test",
            elephant_id="elephant-api-test",
            elephant_name="Elephant Agent API Test",
            surface_bindings=("api",),
        )
        now = datetime(2026, 4, 27, 14, 0, tzinfo=timezone.utc)
        episode = Episode(
            episode_id="episode:api-test",
            state_id="state:api-test",
            personal_model_id=personal_model.profile_id,
            entry_surface="test",
            elephant_id=state.elephant_id,
            status="open",
            started_at=now,
            updated_at=now,
        )
        repository.upsert_episode_state(episode)
        runtime = APIStateService(
            repository=repository,
            recall_runtime=RecallRuntime.from_repository(repository),
        )
        return tmpdir, repository, personal_model, state, episode, runtime

    def _bootstrap(self):
        tmpdir, repository, personal_model, state, episode, runtime = self._build_runtime()
        runtime.ensure_personal_model_state(
            personal_model,
            elephant_id=state.elephant_id,
            state_id=state.state_id,
            episode_id=episode.episode_id,
            sync_source="api.bootstrap-test",
        )
        return tmpdir, repository, personal_model, state, episode, runtime

    def _personal_model_fact_count(self, repository: RuntimeStorageRepository, personal_model_id: str) -> int:
        return len(repository.list_personal_model_facts(personal_model_id=personal_model_id, status="active"))

    def _canonical_facts(
        self,
        repository: RuntimeStorageRepository,
        *,
        personal_model_id: str,
        sync_source: str,
    ):
        return tuple(
            fact
            for fact in repository.list_personal_model_facts(personal_model_id=personal_model_id, status="active")
            if str(fact.metadata.get("sync_source") or "") == sync_source
        )

    def test_ensure_personal_model_state_bootstrap_captures_governed_updates(
        self,
    ) -> None:
        tmpdir, repository, personal_model, state, episode, runtime = self._build_runtime()
        self.addCleanup(tmpdir.cleanup)

        runtime.ensure_personal_model_state(
            personal_model,
            elephant_id=state.elephant_id,
            state_id=state.state_id,
            episode_id=episode.episode_id,
            sync_source="api.bootstrap-test",
        )

        self.assertEqual(self._personal_model_fact_count(repository, personal_model.profile_id), 0)
        canonical_facts = self._canonical_facts(
            repository,
            personal_model_id=personal_model.profile_id,
            sync_source="api.bootstrap-test",
        )
        self.assertEqual(len(canonical_facts), 0)
        self.assertEqual(canonical_facts, ())

    def test_update_identity_state_does_not_capture_personal_model_fact(self) -> None:
        tmpdir, repository, personal_model, state, episode, runtime = self._bootstrap()
        self.addCleanup(tmpdir.cleanup)
        before = self._personal_model_fact_count(repository, personal_model.profile_id)

        updated = runtime.update_identity_state(
            state_id=state.state_id,
            episode_id=episode.episode_id,
            display_name="Elephant Agent Revised",
            elephant_identity_text="Protect continuity and stay exact.",
        )

        self.assertEqual(updated.display_name, "Elephant Agent Revised")
        self.assertEqual(
            self._personal_model_fact_count(repository, personal_model.profile_id),
            before,
        )
        canonical_facts = self._canonical_facts(
            repository,
            personal_model_id=personal_model.profile_id,
            sync_source="api.identity.update",
        )
        self.assertEqual(canonical_facts, ())

    def test_update_user_state_adds_one_governed_memory_capture(self) -> None:
        tmpdir, repository, personal_model, state, episode, runtime = self._bootstrap()
        self.addCleanup(tmpdir.cleanup)
        before = self._personal_model_fact_count(repository, personal_model.profile_id)

        updated = runtime.update_user_state(
            state_id=state.state_id,
            episode_id=episode.episode_id,
            fields={"Preferred name": "Bit"},
        )

        self.assertEqual(updated.preferred_name, "Bit")
        self.assertEqual(
            self._personal_model_fact_count(repository, personal_model.profile_id),
            before + 1,
        )
        canonical_facts = self._canonical_facts(
            repository,
            personal_model_id=personal_model.profile_id,
            sync_source="api.user.update",
        )
        self.assertEqual(len(canonical_facts), 1)
        self.assertEqual(str(canonical_facts[0].metadata.get("state_id") or ""), state.state_id)
        self.assertEqual(str(canonical_facts[0].metadata.get("surface") or ""), "api")
        self.assertEqual(canonical_facts[0].source_episode_ids, (episode.episode_id,))

    def test_update_relationship_state_adds_one_governed_memory_capture(self) -> None:
        tmpdir, repository, personal_model, state, episode, runtime = self._bootstrap()
        self.addCleanup(tmpdir.cleanup)
        before = self._personal_model_fact_count(repository, personal_model.profile_id)

        updated = runtime.update_relationship_state(
            state_id=state.state_id,
            episode_id=episode.episode_id,
            text="Protect focused work windows.",
            append=True,
        )

        self.assertIn("Protect focused work windows.", updated.continuity_notes)
        self.assertEqual(
            self._personal_model_fact_count(repository, personal_model.profile_id),
            before + 1,
        )
        canonical_facts = self._canonical_facts(
            repository,
            personal_model_id=personal_model.profile_id,
            sync_source="api.relationship.update",
        )
        self.assertEqual(len(canonical_facts), 1)
        self.assertEqual(str(canonical_facts[0].metadata.get("state_id") or ""), state.state_id)
        self.assertEqual(str(canonical_facts[0].metadata.get("surface") or ""), "api")
        self.assertEqual(canonical_facts[0].source_episode_ids, (episode.episode_id,))


if __name__ == "__main__":
    unittest.main()
