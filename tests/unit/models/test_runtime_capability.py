from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from packages.auth import AuthProfile
from packages.contracts import Episode
from packages.models.runtime_capability import SurfaceModelProviderCapability
from packages.storage import RuntimeStorageRepository


class SurfaceModelProviderCapabilitySessionProfileTest(unittest.TestCase):
    def _capability(self, tmpdir: str) -> SurfaceModelProviderCapability:
        repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
        repository.bootstrap()
        self.repository = repository
        return SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(tmpdir) / "state" / "secret.key",
        )

    def _episode(self, state_id: str) -> Episode:
        return Episode(
            episode_id="episode:test",
            state_id=state_id,
            personal_model_id="you",
            entry_surface="test",
            status="open",
            started_at=datetime.now(timezone.utc),
        )

    def test_local_cli_baby_does_not_select_provider_session_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            capability = self._capability(tmpdir)
            self.repository.create_state(
                personal_model_id="you",
                state_id="state:local-baby",
                state_anchor="elephant:local-baby",
                elephant_id="local-baby",
                elephant_name="Local Baby",
                identity_mode="baby",
                metadata={
                    "herd_kind": "baby",
                    "backend": "local_cli",
                    "provider_id": "codex",
                    "provider_model": "gpt-5.4",
                    "runtime_id": "local-agent:codex:test",
                },
            )

            profile = capability._profile_for_session(self._episode("state:local-baby"))

        self.assertIsNone(profile)

    def test_provider_baby_pins_provider_model_for_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            capability = self._capability(tmpdir)
            self.repository.upsert_auth_profile(
                AuthProfile(
                    profile_id="provider-openai",
                    provider_id="openai",
                    default_model="gpt-5",
                )
            )
            self.repository.create_state(
                personal_model_id="you",
                state_id="state:provider-baby",
                state_anchor="elephant:provider-baby",
                elephant_id="provider-baby",
                elephant_name="Provider Baby",
                identity_mode="baby",
                metadata={
                    "herd_kind": "baby",
                    "backend": "provider",
                    "provider_id": "openai",
                    "provider_model": "gpt-5.4",
                },
            )

            profile = capability._profile_for_session(self._episode("state:provider-baby"))

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.provider_id, "openai")
        self.assertEqual(profile.default_model, "gpt-5.4")
        self.assertEqual(profile.metadata["session_state_id"], "state:provider-baby")


if __name__ == "__main__":
    unittest.main()
