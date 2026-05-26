from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from apps.reflect.evidence import build_evidence, build_skill_optimization_context
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
from packages.tools.handlers_personal_model import run_personal_model_update
from packages.tools.runtime import ToolInvocation, ToolRuntimeContext
from packages.understanding import PersonalModelUnderstandingSurface
from packages.understanding.personal_model_governance import skill_optimization_candidate_text_from_record


class _AuthoredSkillSurface:
    def __init__(self, root: Path) -> None:
        self._root = root / "elephant-authored"
        self.skill_dirs = {
            "python-development": write_skill_package(
                self._root,
                skill_id="python-development",
                display_name="Python Development",
                summary="Python workflow help",
                instruction_text="Use tool.terminal.exec before tool.file.read when editing Python code.",
                overwrite=True,
                source_kind="elephant-authored",
            ),
            "python-maintenance": write_skill_package(
                self._root,
                skill_id="python-maintenance",
                display_name="Python Maintenance",
                summary="Maintenance workflow help",
                instruction_text="Use tool.web.search before tool.file.read when maintaining Python projects.",
                overwrite=True,
                source_kind="elephant-authored",
            ),
            "workflow-gap": write_skill_package(
                self._root,
                skill_id="workflow-gap",
                display_name="Workflow Gap",
                summary="High-level workflow helper",
                instruction_text="Start by clarifying intent before acting.",
                overwrite=True,
                source_kind="elephant-authored",
            ),
        }
        self.skill_dir = self.skill_dirs["python-development"]

    def inspect_skill(self, skill_id: str, *, session_id: str | None = None):
        del session_id
        definition = load_skill_package_definition(self.skill_dirs[skill_id])
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
            source_path=str(self.skill_dirs[skill_id]),
            skill_ids=(skill_id,),
            loaded_at=datetime.now(timezone.utc),
            status="loaded",
        )

    def list_skills(self):
        return tuple(self.inspect_skill(skill_id) for skill_id in self.skill_dirs)


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
        elephant_id=state.elephant_id,
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


def _seed_skill_affinity(
    surface: PersonalModelUnderstandingSurface,
    *,
    session_id: str,
    personal_model_id: str,
    topic: str,
    text: str,
    skill_id: str,
    index_id: str,
) -> None:
    surface.update_personal_model(
        session_id,
        action="remember",
        lens="world",
        topic=topic,
        text=text,
        reason="seed skill affinity",
        source="learned",
        recall_policy="review",
        personal_model_id=personal_model_id,
        metadata={
            "skill_id": skill_id,
            "index_id": index_id,
            "projection_policy": "skill_shelf_candidate",
        },
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

            _seed_skill_affinity(
                pm_surface,
                session_id="session-skill",
                personal_model_id=state.personal_model_id,
                topic="world.skills.affinity.python_development",
                text="The user repeatedly performs Python editing workflows.",
                skill_id="python-development",
                index_id="python_development",
            )
            _seed_skill_affinity(
                pm_surface,
                session_id="session-skill",
                personal_model_id=state.personal_model_id,
                topic="world.skills.affinity.workflow_gap",
                text="The user repeatedly follows a stable workflow that is not yet encoded in a skill.",
                skill_id="workflow-gap",
                index_id="workflow_gap",
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
            signals = extract_trajectory_signals(
                repository,
                personal_model_id=state.personal_model_id,
                skills=skill_surface.list_skills(),
            )
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

        signal_types = {signal.signal_type for signal in signals}
        self.assertIn("## Workflow Trajectory Signals", evidence)
        self.assertIn("## Skill Evolution Candidates", evidence)
        self.assertIn("## Skill Evolution Candidate Records", evidence)
        self.assertIn('"review_status": "pending"', evidence)
        self.assertIn('"target_scope": "python_development"', evidence)
        self.assertNotIn("别把对话内容写进候选里", evidence)
        self.assertGreaterEqual(len(signals), 1)
        self.assertIn("skill_gap", signal_types)
        self.assertIn("outdated_pattern", signal_types)
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

    def test_learning_agent_write_is_constrained_by_authoritative_candidate_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            state = repository.create_state(elephant_id="elephant-skill", elephant_name="Skill")
            pm_surface = PersonalModelUnderstandingSurface(repository=repository)
            skill_surface = _AuthoredSkillSurface(Path(tmpdir) / "skills")
            now = datetime(2026, 5, 19, tzinfo=timezone.utc)

            _seed_skill_affinity(
                pm_surface,
                session_id="session-skill",
                personal_model_id=state.personal_model_id,
                topic="world.skills.affinity.python_development",
                text="The user repeatedly performs Python editing workflows.",
                skill_id="python-development",
                index_id="python_development",
            )
            for offset in range(6):
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
            _, candidates, candidate_records = build_skill_optimization_context(runtime, job)
            self.assertTrue(candidates)
            self.assertTrue(candidate_records)
            authoritative_record = candidate_records[0]

            repository.upsert_episode(
                Episode(
                    episode_id="reflect-child",
                    state_id=state.state_id,
                    personal_model_id=state.personal_model_id,
                    entry_surface="cli:sub_agent",
                    elephant_id=state.elephant_id,
                    status="open",
                    started_at=now,
                    updated_at=now,
                    parent_episode_id="episode-0",
                    metadata={
                        "episode_kind": "sub_agent",
                        "authoritative_skill_optimization_candidates_json": json.dumps(
                            list(candidate_records),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    },
                )
            )

            with self.assertRaises(ValueError):
                run_personal_model_update(
                    ToolInvocation(
                        invocation_id="invoke:skillopt-unauthorized",
                        tool_id="tool.personal_model.update",
                        session_id="reflect-child",
                        context=ToolRuntimeContext(cwd=Path(tmpdir), personal_model_id=state.personal_model_id),
                        arguments={
                            "action": "remember",
                            "lens": "world",
                            "topic": "world.skills.optimization.new.hallucinated_candidate",
                            "text": "The agent invented a brand new candidate from raw trajectory prose.",
                            "reason": "unauthorized candidate",
                            "source": "learned",
                            "personal_model_id": state.personal_model_id,
                            "metadata": {
                                "candidate_key": "hallucinated_candidate",
                                "review_status": "pending",
                            },
                        },
                    ),
                    surface=pm_surface,
                )

            result = run_personal_model_update(
                ToolInvocation(
                    invocation_id="invoke:skillopt-authorized",
                    tool_id="tool.personal_model.update",
                    session_id="reflect-child",
                    context=ToolRuntimeContext(cwd=Path(tmpdir), personal_model_id=state.personal_model_id),
                    arguments={
                        "action": "remember",
                        "lens": "world",
                        "topic": authoritative_record["topic"],
                        "text": "Bad free-form agent prose that should never survive the write boundary.",
                        "reason": "authorized candidate",
                        "source": "learned",
                        "personal_model_id": state.personal_model_id,
                        "metadata": {
                            "candidate_key": "wrong_key",
                            "confidence": "0.01",
                            "review_status": "pending",
                        },
                    },
                ),
                surface=pm_surface,
            )
            fact = find_candidate_by_topic(
                repository,
                personal_model_id=state.personal_model_id,
                topic=str(authoritative_record["topic"]),
                fact_status="active",
            )

        expected_text = skill_optimization_candidate_text_from_record(authoritative_record)
        self.assertIsNotNone(fact)
        assert fact is not None
        self.assertEqual(fact.text, expected_text)
        self.assertEqual(fact.candidate_key, str(authoritative_record["candidate_key"]))
        self.assertEqual(fact.topic, str(authoritative_record["topic"]))
        self.assertEqual(fact.confidence, float(authoritative_record["confidence"]))
        self.assertIn(expected_text, result["summary"])
        self.assertNotIn("Bad free-form agent prose", fact.text)


if __name__ == "__main__":
    unittest.main()
