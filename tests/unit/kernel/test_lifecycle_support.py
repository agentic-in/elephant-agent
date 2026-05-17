from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from packages.contracts.layers import Episode
from packages.kernel.lifecycle_support import KernelRuntimeIdentity, close_episode_lifecycle, open_episode_lifecycle
from packages.kernel.runtime_support import KernelSourceRequest
from packages.storage.repository_impl import RuntimeStorageRepository


class KernelLifecycleSupportTests(unittest.TestCase):
    def test_gateway_idle_reuse_closes_stale_episode_and_opens_new_episode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            model = repository.ensure_default_personal_model()
            state = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="Gateway",
                elephant_id="elephant-gateway",
                state_id="state-gateway",
                surface_bindings=("gateway:discord:room",),
            )
            state = replace(state, current_context_note="Resume the gateway handoff from the prior episode.")
            repository.upsert_state(state)
            previous_at = datetime(2026, 4, 24, 10, tzinfo=timezone.utc)
            stale_episode = Episode(
                episode_id="episode:gateway-stale",
                state_id=state.state_id,
                personal_model_id=model.personal_model_id,
                entry_surface="gateway:discord:room",
                status="open",
                started_at=previous_at,
                metadata={
                    "policy": "gateway_idle_reuse",
                    "route_id": "gateway-route",
                    "last_activity_at": previous_at.isoformat(),
                },
            )
            repository.upsert_episode(stale_episode)

            lifecycle = open_episode_lifecycle(
                repository,
                KernelSourceRequest(
                    route_id="gateway-route",
                    surface="gateway:discord:room",
                    prompt="new turn after idle",
                    request_id="request-gateway-new",
                    episode_reuse_idle_seconds=1800,
                ),
                KernelRuntimeIdentity(personal_model=model, state=state),
                current=previous_at + timedelta(hours=2),
            )

            stored_stale = repository.load_episode(stale_episode.episode_id)
            self.assertEqual(lifecycle.episode.episode_id, "episode:request-gateway-new")
            self.assertEqual(lifecycle.close_on_completion, False)
            self.assertEqual(tuple(episode.episode_id for episode in lifecycle.idle_closed_episodes), ("episode:gateway-stale",))
            self.assertIsNotNone(stored_stale)
            assert stored_stale is not None
            self.assertEqual(stored_stale.status, "closed")
            self.assertEqual(stored_stale.metadata.get("closed_reason"), "idle_timeout")
            jobs = repository.list_learning_jobs(episode_id=stale_episode.episode_id)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].trigger, "episode_close")
            self.assertEqual(
                lifecycle.episode.metadata.get("opening_resume_snapshot"),
                "Resume the gateway handoff from the prior episode.",
            )

    def test_open_existing_episode_backfills_opening_resume_snapshot_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            model = repository.ensure_default_personal_model()
            state = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="CLI",
                elephant_id="elephant-cli",
                state_id="state-cli-existing",
                current_context_note="Resume from the previous closed episode.",
            )
            existing = Episode(
                episode_id="episode:existing",
                state_id=state.state_id,
                personal_model_id=model.personal_model_id,
                entry_surface="cli",
                status="open",
                started_at=datetime(2026, 4, 24, 10, tzinfo=timezone.utc),
                metadata={"policy": "single_turn"},
            )
            repository.upsert_episode(existing)

            lifecycle = open_episode_lifecycle(
                repository,
                KernelSourceRequest(
                    route_id=existing.episode_id,
                    episode_id=existing.episode_id,
                    surface="cli",
                    prompt="continue",
                ),
                KernelRuntimeIdentity(personal_model=model, state=state),
                current=datetime(2026, 4, 24, 10, 1, tzinfo=timezone.utc),
            )

        self.assertEqual(
            lifecycle.episode.metadata.get("opening_resume_snapshot"),
            "Resume from the previous closed episode.",
        )

    def test_cli_namespace_surfaces_are_session_managed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            model = repository.ensure_default_personal_model()
            state = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="CLI",
                elephant_id="elephant-cli",
                state_id="state-cli-startup",
            )
            episode = Episode(
                episode_id="episode:cli-startup",
                state_id=state.state_id,
                personal_model_id=model.personal_model_id,
                entry_surface="cli",
                status="open",
                started_at=datetime(2026, 4, 24, 10, tzinfo=timezone.utc),
                metadata={"policy": "session_managed"},
            )
            repository.upsert_episode(episode)

            lifecycle = open_episode_lifecycle(
                repository,
                KernelSourceRequest(
                    route_id=episode.episode_id,
                    episode_id=episode.episode_id,
                    surface="cli.startup",
                    prompt="Open the wake surface proactively before the user sends a new message.",
                ),
                KernelRuntimeIdentity(personal_model=model, state=state),
                current=datetime(2026, 4, 24, 10, 1, tzinfo=timezone.utc),
            )

        self.assertFalse(lifecycle.close_on_completion)
        self.assertEqual(lifecycle.episode.status, "open")
        self.assertEqual(lifecycle.episode.metadata.get("policy"), "session_managed")

    def test_explicit_closed_episode_cannot_be_reopened(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            model = repository.ensure_default_personal_model()
            state = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="CLI",
                elephant_id="elephant-cli",
                state_id="state-cli-reopen",
            )
            closed = Episode(
                episode_id="episode:closed-cli",
                state_id=state.state_id,
                personal_model_id=model.personal_model_id,
                entry_surface="cli",
                status="closed",
                started_at=datetime(2026, 4, 24, 10, tzinfo=timezone.utc),
                ended_at=datetime(2026, 4, 24, 10, 1, tzinfo=timezone.utc),
                metadata={"policy": "single_turn", "closed_reason": "final_response"},
            )
            repository.upsert_episode(closed)

            with self.assertRaisesRegex(ValueError, "closed episode cannot be reopened"):
                open_episode_lifecycle(
                    repository,
                    KernelSourceRequest(
                        route_id=closed.episode_id,
                        episode_id=closed.episode_id,
                        surface="cli",
                        prompt="continue in the existing wake TUI",
                    ),
                    KernelRuntimeIdentity(personal_model=model, state=state),
                    current=datetime(2026, 4, 24, 10, 2, tzinfo=timezone.utc),
                )
            stored = repository.load_episode(closed.episode_id)

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, "closed")

    def test_close_episode_does_not_foreground_update_state_continuation_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            model = repository.ensure_default_personal_model()
            state = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="CLI",
                elephant_id="elephant-cli",
                state_id="state-cli",
            )
            episode = Episode(
                episode_id="episode:close-boundary",
                state_id=state.state_id,
                personal_model_id=model.personal_model_id,
                entry_surface="cli",
                status="open",
                started_at=datetime(2026, 4, 24, 10, tzinfo=timezone.utc),
                metadata={"policy": "single_turn"},
            )
            repository.upsert_episode(episode)
            lifecycle = type(
                "_Lifecycle",
                (),
                {"episode": episode, "close_on_completion": True},
            )()

            closed = close_episode_lifecycle(
                repository,
                lifecycle,
                summary="Carry forward the dashboard IA decision.",
                current=datetime(2026, 4, 24, 11, tzinfo=timezone.utc),
            )
            refreshed_state = repository.load_state(state.state_id)

        self.assertEqual(closed.status, "closed")
        self.assertIsNotNone(refreshed_state)
        assert refreshed_state is not None
        self.assertEqual(refreshed_state.current_context_note, "")


if __name__ == "__main__":
    unittest.main()
