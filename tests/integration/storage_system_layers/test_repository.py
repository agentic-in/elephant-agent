from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from datetime import datetime, timezone
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts import (
    Episode,
    Loop,
    PersonalModel,
    SemanticIndexEntry,
    Step,
)
from packages.operator.local_agents import LocalAgentRuntimeRecord
from packages.storage import RuntimeStorageRepository
from packages.storage.repository_bootstrap_methods import LEGACY_STORAGE_TABLES


def _singular_table_name(table_name: str) -> str:
    if table_name.endswith("ies"):
        return f"{table_name[:-3]}y"
    if table_name.endswith("s"):
        return table_name[:-1]
    return table_name


def _removed_legacy_storage_method_names() -> tuple[str, ...]:
    table_method_names: list[str] = []
    for table_name in sorted(LEGACY_STORAGE_TABLES):
        singular = _singular_table_name(table_name)
        table_method_names.extend(
            [
                f"upsert_{singular}",
                f"load_{singular}",
                f"list_{table_name}",
            ]
        )
    return tuple(table_method_names)


class StorageSystemLayerRepositoryTest(unittest.TestCase):
    def test_legacy_repository_methods_are_removed(self) -> None:
        repository = RuntimeStorageRepository(Path("/tmp/elephant-unused.sqlite3"))

        for method_name in (
            "upsert_profile",
            "load_profile",
            "upsert_session",
            "load_session",
            "upsert_activity_graph",
            "load_activity_graph",
            "load_" + "agent_run",
            "upsert_evidence_record_bundle",
            "load_evidence_record_bundle",
                "append_" + "memory_ledger",
        ):
            self.assertFalse(hasattr(repository, method_name), method_name)

    def test_default_personal_model_creation_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            created = repository.ensure_default_personal_model()
            again = repository.ensure_default_personal_model(display_name="Ignored")

        self.assertEqual(created.personal_model_id, "you")
        self.assertEqual(created.display_name, "You")
        self.assertEqual(again.personal_model_id, created.personal_model_id)
        self.assertEqual(again.display_name, created.display_name)

    def test_personal_model_round_trips_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            repository.upsert_personal_model(
                PersonalModel(
                    personal_model_id="pm-alpha",
                    display_name="Alpha",
                    status="active",
                    metadata={"source": "test"},
                )
            )
            loaded = repository.load_personal_model("pm-alpha")
            listed = repository.list_personal_models()

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.display_name, "Alpha")
        self.assertEqual(loaded.metadata, {"source": "test"})
        self.assertEqual(tuple(model.personal_model_id for model in listed), ("pm-alpha",))

    def test_elephant_state_create_switch_list_and_delete_preserves_personal_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            personal_model = repository.ensure_default_personal_model()
            alpha = repository.create_state(
                personal_model_id=personal_model.personal_model_id,
                elephant_id="elephant-alpha",
                elephant_name="Alpha",
                posture="direct",
                capability_boundaries=("shell",),
                surface_bindings=("cli",),
            )
            beta = repository.create_state(
                personal_model_id=personal_model.personal_model_id,
                elephant_id="elephant-beta",
                elephant_name="Beta",
            )
            alpha_lookup = repository.list_states(elephant_id="elephant-alpha")
            alpha_anchor_lookup = repository.list_states(state_anchor=alpha.state_anchor)
            selected = repository.switch_state(alpha.state_id)
            repository.delete_state(alpha.state_id)

            remaining = repository.list_states(personal_model_id=personal_model.personal_model_id)
            current = repository.current_state()
            persisted_personal_model = repository.load_personal_model(personal_model.personal_model_id)

        self.assertEqual(selected.elephant_name, "Alpha")
        self.assertEqual(selected.capability_boundaries, ("shell",))
        self.assertEqual(selected.surface_bindings, ("cli",))
        self.assertEqual(tuple(state.elephant_id for state in alpha_lookup), ("elephant-alpha",))
        self.assertEqual(tuple(state.elephant_id for state in alpha_anchor_lookup), ("elephant-alpha",))
        self.assertEqual(tuple(state.elephant_id for state in remaining), ("elephant-beta",))
        self.assertEqual(beta.elephant_name, "Beta")
        self.assertIsNone(current)
        self.assertIsNotNone(persisted_personal_model)

    def test_episode_loop_and_step_round_trip_without_legacy_evidence(self) -> None:
        now = datetime(2026, 4, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            state = repository.create_state(elephant_id="elephant-alpha", elephant_name="Alpha")
            episode = Episode(
                episode_id="episode-1",
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                entry_surface="cli",
                status="open",
                started_at=now,
                metadata={"trace": "episode"},
            )
            loop = Loop(
                loop_id="loop-1",
                episode_id=episode.episode_id,
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                trigger_type="user_message",
                status="complete",
                started_at=now,
                summary="Handled one turn.",
            )
            step = Step(
                step_id="step-1",
                loop_id=loop.loop_id,
                episode_id=episode.episode_id,
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                phase="acting",
                action="call_model",
                status="completed",
                sequence=0,
                created_at=now,
                summary="Generated response.",
                payload_refs=("payload:1",),
            )

            repository.upsert_episode(episode)
            repository.upsert_loop(loop)
            repository.upsert_step(step)

            loaded_episode = repository.load_episode(episode.episode_id)
            loaded_loop = repository.load_loop(loop.loop_id)
            loaded_step = repository.load_step(step.step_id)

        self.assertEqual(loaded_episode, episode)
        self.assertEqual(loaded_loop, loop)
        self.assertEqual(loaded_step, step)

    def test_list_episodes_can_filter_and_limit_recent_history(self) -> None:
        now = datetime(2026, 4, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            alpha = repository.create_state(
                personal_model_id="pm-alpha",
                elephant_id="elephant-alpha",
                elephant_name="Alpha",
            )
            beta = repository.create_state(
                personal_model_id="pm-beta",
                elephant_id="elephant-beta",
                elephant_name="Beta",
            )
            for episode in (
                Episode(
                    episode_id="episode-alpha-old",
                    state_id=alpha.state_id,
                    personal_model_id=alpha.personal_model_id,
                    elephant_id=alpha.elephant_id,
                    entry_surface="cli",
                    status="closed",
                    started_at=now,
                ),
                Episode(
                    episode_id="episode-alpha-open",
                    state_id=alpha.state_id,
                    personal_model_id=alpha.personal_model_id,
                    elephant_id=alpha.elephant_id,
                    entry_surface="cli",
                    status="open",
                    started_at=now.replace(day=24),
                ),
                Episode(
                    episode_id="episode-alpha-new",
                    state_id=alpha.state_id,
                    personal_model_id=alpha.personal_model_id,
                    elephant_id=alpha.elephant_id,
                    entry_surface="cli",
                    status="closed",
                    started_at=now.replace(day=25),
                ),
                Episode(
                    episode_id="episode-beta-new",
                    state_id=beta.state_id,
                    personal_model_id=beta.personal_model_id,
                    elephant_id=beta.elephant_id,
                    entry_surface="cli",
                    status="closed",
                    started_at=now.replace(day=26),
                ),
            ):
                repository.upsert_episode(episode)

            recent_alpha = repository.list_episodes(
                personal_model_id=alpha.personal_model_id,
                status="closed",
                limit=1,
                newest_first=True,
            )
            alpha_by_state = repository.list_episodes(state_id=alpha.state_id)
            alpha_by_elephant = repository.list_episodes(elephant_id=alpha.elephant_id)

        self.assertEqual(
            tuple(episode.episode_id for episode in recent_alpha),
            ("episode-alpha-new",),
        )
        self.assertEqual(
            tuple(episode.episode_id for episode in alpha_by_state),
            ("episode-alpha-old", "episode-alpha-open", "episode-alpha-new"),
        )
        self.assertEqual(
            tuple(episode.episode_id for episode in alpha_by_elephant),
            ("episode-alpha-old", "episode-alpha-open", "episode-alpha-new"),
        )

    def test_list_steps_can_filter_timebox_and_limit_recent_history(self) -> None:
        now = datetime(2026, 4, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            alpha = repository.create_state(
                personal_model_id="pm-alpha",
                elephant_id="elephant-alpha",
                elephant_name="Alpha",
            )
            beta = repository.create_state(
                personal_model_id="pm-beta",
                elephant_id="elephant-beta",
                elephant_name="Beta",
            )
            for state, episode_id, loop_id in (
                (alpha, "episode-alpha", "loop-alpha"),
                (beta, "episode-beta", "loop-beta"),
            ):
                repository.upsert_episode(
                    Episode(
                        episode_id=episode_id,
                        state_id=state.state_id,
                        personal_model_id=state.personal_model_id,
                        entry_surface="cli",
                        status="closed",
                        started_at=now,
                    )
                )
                repository.upsert_loop(
                    Loop(
                        loop_id=loop_id,
                        episode_id=episode_id,
                        state_id=state.state_id,
                        personal_model_id=state.personal_model_id,
                        trigger_type="turn",
                        status="closed",
                        started_at=now,
                    )
                )
            for step in (
                Step(
                    step_id="step-alpha-old",
                    loop_id="loop-alpha",
                    episode_id="episode-alpha",
                    state_id=alpha.state_id,
                    personal_model_id=alpha.personal_model_id,
                    phase="observation",
                    action="record_input",
                    status="completed",
                    sequence=1,
                    created_at=now,
                    summary="alpha old",
                ),
                Step(
                    step_id="step-alpha-new",
                    loop_id="loop-alpha",
                    episode_id="episode-alpha",
                    state_id=alpha.state_id,
                    personal_model_id=alpha.personal_model_id,
                    phase="observation",
                    action="record_input",
                    status="completed",
                    sequence=2,
                    created_at=now.replace(day=25),
                    summary="alpha new",
                ),
                Step(
                    step_id="step-beta-new",
                    loop_id="loop-beta",
                    episode_id="episode-beta",
                    state_id=beta.state_id,
                    personal_model_id=beta.personal_model_id,
                    phase="observation",
                    action="record_input",
                    status="completed",
                    sequence=1,
                    created_at=now.replace(day=26),
                    summary="beta new",
                ),
            ):
                repository.upsert_step(step)

            recent_alpha = repository.list_steps(
                state_id=alpha.state_id,
                personal_model_id=alpha.personal_model_id,
                created_at_start=now.replace(day=24),
                limit=1,
                newest_first=True,
            )
            alpha_loops = repository.list_loops(
                state_id=alpha.state_id,
                personal_model_id=alpha.personal_model_id,
                trigger_type="turn",
                status="closed",
            )
            alpha_by_loop = repository.list_steps(loop_id="loop-alpha")

        self.assertEqual(tuple(step.step_id for step in recent_alpha), ("step-alpha-new",))
        self.assertEqual(tuple(loop.loop_id for loop in alpha_loops), ("loop-alpha",))
        self.assertEqual(tuple(step.step_id for step in alpha_by_loop), ("step-alpha-old", "step-alpha-new"))

    def test_legacy_storage_methods_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            for method_name in _removed_legacy_storage_method_names():
                self.assertFalse(hasattr(repository, method_name), method_name)

    def test_elephant_delete_removes_state_scoped_semantic_rows_only(self) -> None:
        now = datetime(2026, 4, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            state = repository.create_state(elephant_id="elephant-alpha", elephant_name="Alpha")
            repository.upsert_semantic_index_entry(
                SemanticIndexEntry(
                    semantic_index_entry_id="semantic-state",
                    owner_scope="state",
                    source_id="source-state",
                    provider_id="local-elephant",
                    model_id="elephant-embedding",
                    dimensions=384,
                    content_hash="sha256:state",
                    personal_model_id=state.personal_model_id,
                    state_id=state.state_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            repository.upsert_semantic_index_entry(
                SemanticIndexEntry(
                    semantic_index_entry_id="semantic-personal",
                    owner_scope="personal_model",
                    source_id="source-personal",
                    provider_id="local-elephant",
                    model_id="elephant-embedding",
                    dimensions=384,
                    content_hash="sha256:personal",
                    personal_model_id=state.personal_model_id,
                    created_at=now,
                    updated_at=now,
                )
            )

            repository.delete_state(state.state_id)

            state_semantic = repository.load_semantic_index_entry("semantic-state")
            personal_semantic = repository.load_semantic_index_entry("semantic-personal")
            personal_model = repository.load_personal_model(state.personal_model_id)

        self.assertIsNone(state_semantic)
        self.assertIsNotNone(personal_semantic)
        self.assertIsNotNone(personal_model)

    def test_local_agent_runtime_round_trips_and_upserts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            initial = LocalAgentRuntimeRecord(
                runtime_id="local-agent:codex:test",
                provider_id="codex",
                command="codex",
                display_name="Codex",
                resolved_path="/tmp/codex",
                version="codex 1",
                status="detected",
                auth_status="configured",
                source="env",
                default_model="gpt-5.4",
                can_execute=True,
                role_title="coding implementer",
                role_prompt="Implement changes.",
                detected_at="2026-05-23T00:00:00+00:00",
                metadata={"adapter": "argv_prompt"},
            )
            updated = replace(initial, version="codex 2", last_error="version changed")

            repository.upsert_local_agent_runtime(initial)
            repository.upsert_local_agent_runtime(updated)

            loaded = repository.load_local_agent_runtime(initial.runtime_id)
            listed = repository.list_local_agent_runtimes()

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.version, "codex 2")
        self.assertEqual(loaded.last_error, "version changed")
        self.assertTrue(loaded.can_execute)
        self.assertEqual(loaded.metadata, {"adapter": "argv_prompt"})
        self.assertEqual(tuple(record.runtime_id for record in listed), (initial.runtime_id,))


if __name__ == "__main__":
    unittest.main()
