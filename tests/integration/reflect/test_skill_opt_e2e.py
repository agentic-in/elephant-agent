from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from apps.reflect.evidence import build_evidence
from apps.reflect.features import resolve_features
from packages.contracts import Episode, Loop, Step
from packages.contracts.runtime import LearningJob
from packages.reflect import (
    aggregate_signals,
    apply_approved_optimization,
    extract_trajectory_signals,
    find_candidate_by_ref,
    find_candidate_by_topic,
    mark_candidate_review_status,
    optimization_candidate_topic,
    persist_optimization_candidate,
)
from packages.skills.authoring import write_skill_package
from packages.skills.runtime import SkillManifestLoadRecord, load_skill_package_definition
from packages.storage import RuntimeStorageRepository
from packages.understanding import PersonalModelUnderstandingSurface


class _AuthoredSkillSurface:
    def __init__(self, root: Path) -> None:
        self._root = root / "elephant-authored"
        self.skill_dir = write_skill_package(
            self._root,
            skill_id="python-development",
            display_name="Python Development",
            summary="Python workflow help",
            instruction_text="Use tool.terminal.exec before tool.file.read when editing Python code.",
            overwrite=True,
            source_kind="elephant-authored",
        )

    def inspect_skill(self, skill_id: str, *, session_id: str | None = None):
        del session_id
        definition = load_skill_package_definition(self.skill_dir)
        metadata = dict(definition.metadata)
        metadata.update(
            {
                "source_kind": "elephant-authored",
                "source_id": "elephant-authored",
                "hub_reference": f"elephant-authored:{skill_id}",
            }
        )
        return replace(definition, metadata=metadata)

    def update_authored_skill(self, skill_id: str, *, instruction_text: str | None = None, **_: object) -> SkillManifestLoadRecord:
        current = self.inspect_skill(skill_id)
        write_skill_package(
            self._root,
            skill_id=skill_id,
            display_name=current.display_name,
            summary=current.summary,
            instruction_text=instruction_text or current.instruction_text,
            overwrite=True,
            source_kind="elephant-authored",
        )
        return SkillManifestLoadRecord(
            source_path=str(self.skill_dir),
            skill_ids=(skill_id,),
            loaded_at=datetime.now(timezone.utc),
            status="loaded",
        )

    def list_skills(self):
        return (self.inspect_skill("python-development"),)


def _seed_closed_episode(
    repository: RuntimeStorageRepository,
    *,
    state,
    episode_id: str,
    started_at: datetime,
    tools: tuple[str, ...],
) -> None:
    episode = Episode(
        episode_id=episode_id,
        state_id=state.state_id,
        personal_model_id=state.personal_model_id,
        entry_surface="cli",
        status="closed",
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=3),
        exit_summary="closed episode for skill optimization",
    )
    loop = Loop(
        loop_id=f"loop:{episode_id}",
        episode_id=episode_id,
        state_id=state.state_id,
        personal_model_id=state.personal_model_id,
        trigger_type="user_message",
        status="completed",
        started_at=started_at,
        summary="one workflow loop",
    )
    repository.upsert_episode(episode)
    repository.upsert_loop(loop)
    repository.upsert_step(
        Step(
            step_id=f"step:{episode_id}:input",
            loop_id=loop.loop_id,
            episode_id=episode_id,
            state_id=state.state_id,
            personal_model_id=state.personal_model_id,
            phase="observation",
            action="record_input",
            status="completed",
            sequence=0,
            created_at=started_at,
            summary="user request captured",
            metadata={"user_query": "帮我批量改 Python 文件，但别把对话内容写进候选里"},
        )
    )
    for index, tool_name in enumerate(tools, start=1):
        repository.upsert_step(
            Step(
                step_id=f"step:{episode_id}:{index}",
                loop_id=loop.loop_id,
                episode_id=episode_id,
                state_id=state.state_id,
                personal_model_id=state.personal_model_id,
                phase="acting",
                action="call_tool",
                status="completed",
                sequence=index,
                created_at=started_at + timedelta(seconds=index),
                summary=f"called {tool_name}",
                metadata={"tool_name": tool_name},
            )
        )


class SkillOptimizationEndToEndTest(unittest.TestCase):
    def test_skill_review_flow_can_extract_persist_and_apply_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-skill", elephant_name="Skill")
            pm_surface = PersonalModelUnderstandingSurface(repository=repository)
            skill_surface = _AuthoredSkillSurface(Path(tmpdir) / "skills")
            now = datetime(2026, 5, 19, tzinfo=timezone.utc)

            pm_surface.update_personal_model(
                "session-skill",
                action="remember",
                lens="world",
                topic="world.skills.affinity.python_development",
                text="The user repeatedly performs Python editing workflows.",
                reason="seed skill affinity",
                source="learned",
                recall_policy="review",
                personal_model_id=state.personal_model_id,
                metadata={
                    "skill_id": "python-development",
                    "index_id": "python_development",
                    "projection_policy": "skill_shelf_candidate",
                },
            )

            for offset in range(10):
                _seed_closed_episode(
                    repository,
                    state=state,
                    episode_id=f"episode-{offset}",
                    started_at=now - timedelta(days=offset + 1),
                    tools=("tool.terminal.exec", "tool.file.read", "tool.terminal.exec"),
                )

            runtime = type(
                "_Runtime",
                (),
                {
                    "repository": repository,
                    "list_skills": skill_surface.list_skills,
                },
            )()
            job = LearningJob(
                job_id="job-skill-review",
                job_type="episode_boundary_learning",
                trigger="skill_review",
                status="queued",
                personal_model_id=state.personal_model_id,
                state_id=state.state_id,
                episode_id="episode-0",
            )

            evidence = build_evidence(runtime, job, resolve_features("skill_review"))
            signals = extract_trajectory_signals(repository, personal_model_id=state.personal_model_id)
            candidates = aggregate_signals(
                signals,
                repository,
                personal_model_id=state.personal_model_id,
                skills=skill_surface.list_skills(),
            )
            self.assertTrue(candidates)
            candidate = candidates[0]
            persisted = persist_optimization_candidate(
                pm_surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                candidate=candidate,
            )
            pending = find_candidate_by_topic(
                repository,
                personal_model_id=state.personal_model_id,
                topic=optimization_candidate_topic(candidate),
                fact_status="active",
            )
            approved = mark_candidate_review_status(
                pm_surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                ref=persisted["claim"]["ref"],
                review_status="approved",
            )
            applied = apply_approved_optimization(
                pm_surface,
                skill_surface,
                "session-skill",
                personal_model_id=state.personal_model_id,
                ref=approved["claim"]["ref"],
            )
            applied_record = find_candidate_by_ref(
                repository,
                personal_model_id=state.personal_model_id,
                ref=applied["ref"],
                fact_status="active",
            )
            updated_skill = load_skill_package_definition(skill_surface.skill_dir)

        self.assertIn("## Trajectory Signals", evidence)
        self.assertIn("## Optimization Candidates", evidence)
        self.assertNotIn("别把对话内容写进候选里", evidence)
        self.assertGreaterEqual(len(signals), 1)
        self.assertEqual(candidate.optimization_type, "update_procedure")
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending.review_status, "pending")
        self.assertEqual(pending.recall_policy, "review")
        self.assertTrue(applied["applied"])
        self.assertIsNotNone(applied_record)
        assert applied_record is not None
        self.assertEqual(applied_record.review_status, "applied")
        self.assertIn("Reviewed optimization", updated_skill.instruction_text)
        self.assertIn("tool.terminal.exec -> tool.file.read", updated_skill.instruction_text)


if __name__ == "__main__":
    unittest.main()
