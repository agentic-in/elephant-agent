from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

from packages.contracts.layers import Episode, Loop, PersonalModel, State, Step
from packages.kernel.episode_state_machine import close_episode
from packages.kernel.lifecycle_support import (
    KernelEpisodeLifecycle,
    KernelRuntimeIdentity,
    KernelStepRecorder,
    close_episode_lifecycle,
    open_episode_lifecycle,
    resolve_runtime_identity,
)
from packages.kernel.runtime_support import KernelSourceRequest
from packages.storage.repository_impl import RuntimeStorageRepository


class _GatewayReuseStorage:
    def __init__(self, episode: Episode) -> None:
        self.episode = episode
        self.list_episode_calls: list[dict[str, object]] = []
        self.upserted_episode: Episode | None = None

    def list_episodes(self, **kwargs: object) -> tuple[Episode, ...]:
        self.list_episode_calls.append(dict(kwargs))
        if kwargs != {
            "state_id": "state-gateway",
            "status": "open",
            "newest_first": True,
        }:
            raise AssertionError(f"unexpected broad episode query: {kwargs!r}")
        return (self.episode,)

    def upsert_episode(self, episode: Episode) -> None:
        self.upserted_episode = episode
        self.episode = episode


class _CloseEpisodeStorage:
    def __init__(self, episode: Episode) -> None:
        self.episode = episode
        self.list_loop_calls: list[dict[str, object]] = []
        self.enqueued_loop_id = ""

    def load_episode(self, episode_id: str) -> Episode | None:
        return self.episode if episode_id == self.episode.episode_id else None

    def upsert_episode(self, episode: Episode) -> None:
        self.episode = episode

    def list_loops(self, **kwargs: object) -> tuple[object, ...]:
        self.list_loop_calls.append(dict(kwargs))
        if kwargs != {
            "episode_id": self.episode.episode_id,
            "limit": 1,
            "newest_first": True,
        }:
            raise AssertionError(f"unexpected broad loop query: {kwargs!r}")
        return (SimpleNamespace(loop_id="loop:latest"),)

    def enqueue_learning_job(self, **kwargs: object) -> object:
        self.enqueued_loop_id = str(kwargs.get("loop_id") or "")
        return SimpleNamespace(job_id="job:episode-close")


class _FailingCloseEpisodeStorage(_CloseEpisodeStorage):
    def enqueue_learning_job(self, **kwargs: object) -> object:
        raise RuntimeError("enqueue failed")


class _FailingSummaryIndexer:
    def index_episode_exit(self, episode: Episode) -> None:
        raise RuntimeError("index failed")


class _FailingStepIndexer:
    def index_step(self, step: Step) -> None:
        raise RuntimeError("step index failed")


class _StepRecorderStorage:
    def __init__(self) -> None:
        self.steps: list[Step] = []

    def list_steps(self, **kwargs: object) -> tuple[Step, ...]:
        return tuple(self.steps)

    def upsert_step(self, step: Step) -> None:
        self.steps.append(step)


class KernelLifecycleSupportTests(unittest.TestCase):
    def test_foreground_identity_resolution_switches_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            model = repository.ensure_default_personal_model()
            seed = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="Seed",
                elephant_id="seed",
                state_id="state:seed",
            )
            nova = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="Nova",
                elephant_id="nova",
                state_id="state:nova",
            )
            current = datetime(2026, 4, 24, 10, tzinfo=timezone.utc)
            repository.switch_state(seed.state_id, selected_at=current)

            identity = resolve_runtime_identity(
                repository,
                KernelSourceRequest(
                    route_id="episode:nova",
                    prompt="foreground turn",
                    surface="cli",
                    state_id=nova.state_id,
                ),
                current=current + timedelta(minutes=1),
            )
            selected = repository.current_state()

        self.assertEqual(identity.state.state_id, nova.state_id)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.state_id, nova.state_id)

    def test_background_identity_resolution_preserves_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            model = repository.ensure_default_personal_model()
            seed = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="Seed",
                elephant_id="seed",
                state_id="state:seed",
            )
            nova = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="Nova",
                elephant_id="nova",
                state_id="state:nova",
            )
            current = datetime(2026, 4, 24, 10, tzinfo=timezone.utc)
            repository.switch_state(nova.state_id, selected_at=current)

            identity = resolve_runtime_identity(
                repository,
                KernelSourceRequest(
                    route_id="episode:seed:reflect",
                    prompt="background learning turn",
                    surface="learning.sub_agent",
                    source_event_type="turn.internal",
                    source_payload={"context_mode": "learning_agent"},
                    owner_scope="sub_agent",
                    state_id=seed.state_id,
                ),
                current=current + timedelta(minutes=1),
            )
            selected = repository.current_state()

        self.assertEqual(identity.state.state_id, seed.state_id)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.state_id, nova.state_id)

    def test_gateway_idle_reuse_queries_only_open_candidate_episodes(self) -> None:
        current = datetime(2026, 4, 24, 10, 1, tzinfo=timezone.utc)
        model = PersonalModel(personal_model_id="you")
        state = State(
            state_id="state-gateway",
            personal_model_id=model.personal_model_id,
            state_anchor="elephant:gateway",
            elephant_id="gateway",
        )
        episode = Episode(
            episode_id="episode:gateway-current",
            state_id=state.state_id,
            personal_model_id=model.personal_model_id,
            entry_surface="gateway:discord:room",
            status="open",
            started_at=current - timedelta(minutes=1),
            metadata={
                "policy": "gateway_idle_reuse",
                "route_id": "gateway-route",
                "last_activity_at": (current - timedelta(minutes=1)).isoformat(),
            },
        )
        storage = _GatewayReuseStorage(episode)

        lifecycle = open_episode_lifecycle(
            storage,  # type: ignore[arg-type]
            KernelSourceRequest(
                route_id="gateway-route",
                surface="gateway:discord:room",
                prompt="reuse this turn",
                request_id="request-gateway-reuse",
                episode_reuse_idle_seconds=1800,
            ),
            KernelRuntimeIdentity(personal_model=model, state=state),
            current=current,
        )

        self.assertEqual(lifecycle.episode.episode_id, episode.episode_id)
        self.assertEqual(
            storage.list_episode_calls,
            [{"state_id": "state-gateway", "status": "open", "newest_first": True}],
        )

    def test_close_episode_uses_bounded_latest_loop_query_for_learning_job(self) -> None:
        episode = Episode(
            episode_id="episode:close",
            state_id="state:close",
            personal_model_id="you",
            entry_surface="cli",
            status="open",
            started_at=datetime(2026, 4, 24, 10, tzinfo=timezone.utc),
        )
        storage = _CloseEpisodeStorage(episode)

        closed = close_episode(
            storage,  # type: ignore[arg-type]
            episode.episode_id,
            reason="final_response",
            summary="done",
            current=datetime(2026, 4, 24, 10, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(closed.status, "closed")
        self.assertEqual(storage.enqueued_loop_id, "loop:latest")
        self.assertEqual(
            storage.list_loop_calls,
            [{"episode_id": "episode:close", "limit": 1, "newest_first": True}],
        )

    def test_close_episode_logs_best_effort_side_effect_failures(self) -> None:
        episode = Episode(
            episode_id="episode:close-log",
            state_id="state:close",
            personal_model_id="you",
            entry_surface="cli",
            status="open",
            started_at=datetime(2026, 4, 24, 10, tzinfo=timezone.utc),
        )
        storage = _FailingCloseEpisodeStorage(episode)

        with self.assertLogs("packages.kernel.episode_state_machine", level="WARNING") as captured:
            closed = close_episode(
                storage,  # type: ignore[arg-type]
                episode.episode_id,
                reason="final_response",
                summary="done",
                current=datetime(2026, 4, 24, 10, 1, tzinfo=timezone.utc),
                semantic_summary_indexer=_FailingSummaryIndexer(),
            )

        self.assertEqual(closed.status, "closed")
        self.assertIn(
            "episode exit summary indexing failed for episode:close-log: index failed",
            "\n".join(captured.output),
        )
        self.assertIn(
            "episode close learning enqueue failed for episode:close-log: enqueue failed",
            "\n".join(captured.output),
        )

    def test_lifecycle_helpers_log_best_effort_index_failures(self) -> None:
        episode = Episode(
            episode_id="episode:lifecycle-log",
            state_id="state:lifecycle",
            personal_model_id="you",
            entry_surface="cli",
            status="open",
            started_at=datetime(2026, 4, 24, 10, tzinfo=timezone.utc),
        )
        storage = _GatewayReuseStorage(episode)
        loop = Loop(
            loop_id="loop:lifecycle-log",
            episode_id=episode.episode_id,
            state_id=episode.state_id,
            personal_model_id=episode.personal_model_id,
            trigger_type="user_turn",
            status="running",
            started_at=episode.started_at,
        )
        step_storage = _StepRecorderStorage()

        with self.assertLogs("packages.kernel.lifecycle_support", level="WARNING") as captured:
            recorder = KernelStepRecorder(
                step_storage,  # type: ignore[arg-type]
                loop,
                semantic_summary_indexer=_FailingStepIndexer(),
            )
            recorder.record(
                phase="reasoning",
                action="compose",
                status="completed",
                current=datetime(2026, 4, 24, 10, 1, tzinfo=timezone.utc),
            )
            close_episode_lifecycle(
                storage,  # type: ignore[arg-type]
                KernelEpisodeLifecycle(episode=episode, close_on_completion=True),
                summary="done",
                current=datetime(2026, 4, 24, 10, 2, tzinfo=timezone.utc),
                semantic_summary_indexer=_FailingSummaryIndexer(),
            )

        output = "\n".join(captured.output)
        self.assertIn("step indexing failed for step:loop:lifecycle-log:0: step index failed", output)
        self.assertIn(
            "episode lifecycle exit indexing failed for episode:lifecycle-log: index failed",
            output,
        )

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

    def test_close_episode_lifecycle_cleans_session_resources(self) -> None:
        class _ResourceManager:
            def __init__(self) -> None:
                self.cleaned: list[str] = []

            def cleanup_session(self, session_id: str) -> bool:
                self.cleaned.append(session_id)
                return True

        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            model = repository.ensure_default_personal_model()
            state = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="CLI",
                elephant_id="elephant-cli",
                state_id="state-cli-cleanup",
            )
            episode = Episode(
                episode_id="episode:cleanup-session",
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
            manager = _ResourceManager()

            closed = close_episode_lifecycle(
                repository,
                lifecycle,
                summary="close and cleanup sandbox session",
                current=datetime(2026, 4, 24, 11, tzinfo=timezone.utc),
                session_resource_manager=manager,
            )

        self.assertEqual(closed.status, "closed")
        self.assertEqual(manager.cleaned, ["episode:cleanup-session"])


if __name__ == "__main__":
    unittest.main()
