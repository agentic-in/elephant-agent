from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from apps.reflect.evidence import build_evidence
from apps.reflect.features import resolve_features
from apps.reflect.runner import _assemble_system_prompt
from packages.contracts.runtime import LearningJob


class _Repository:
    def load_episode(self, episode_id: str) -> SimpleNamespace:
        return SimpleNamespace(exit_summary="episode summary")

    def list_personal_model_facts(self, **_: object):
        return (
            SimpleNamespace(
                lens="world",
                text="用户经常做 Python 自动化。",
                metadata={
                    "topic": "world.skills.affinity.python_development",
                    "skill_id": "python-development",
                    "index_id": "python_development",
                },
            ),
        )

    def list_episodes(self):
        return (
            SimpleNamespace(
                episode_id="episode",
                personal_model_id="pm",
                status="closed",
                started_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                episode_id="episode-2",
                personal_model_id="pm",
                status="closed",
                started_at=datetime(2026, 5, 17, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                episode_id="episode-3",
                personal_model_id="pm",
                status="closed",
                started_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
            ),
        )

    def list_loops(self, *, episode_id=None):
        episode_id = episode_id or "episode"
        return (SimpleNamespace(loop_id=f"loop-{episode_id}", episode_id=episode_id, started_at=datetime(2026, 5, 18, tzinfo=timezone.utc)),)

    def list_steps(self, *, loop_id=None):
        loop_id = loop_id or "loop-episode"
        return (
            SimpleNamespace(loop_id=loop_id, action="record_input", status="completed", sequence=1, created_at=datetime(2026, 5, 18, tzinfo=timezone.utc), metadata={"user_query": "帮我批量修改 Python 文件"}),
            SimpleNamespace(loop_id=loop_id, action="call_tool", status="completed", sequence=2, created_at=datetime(2026, 5, 18, tzinfo=timezone.utc), metadata={"tool_name": "tool.terminal.exec"}),
            SimpleNamespace(loop_id=loop_id, action="call_tool", status="completed", sequence=3, created_at=datetime(2026, 5, 18, tzinfo=timezone.utc), metadata={"tool_name": "tool.file.read"}),
            SimpleNamespace(loop_id=loop_id, action="call_model", status="completed", sequence=4, created_at=datetime(2026, 5, 18, tzinfo=timezone.utc), metadata={"assistant_response": "我先检查文件。"}),
        )


class SkillOptimizationFeatureTest(unittest.TestCase):
    def test_skill_review_trigger_resolves_skill_optimization_and_skills(self) -> None:
        features = resolve_features("skill_review")

        self.assertEqual(tuple(feature.feature_id for feature in features), ("skill_optimization", "skills"))

    def test_dream_prompt_mentions_skill_optimization_topics(self) -> None:
        prompt = _assemble_system_prompt(resolve_features("dream"), conservatism="medium")

        self.assertIn("world.skills.optimization.<scope>.<candidate_key>", prompt)
        self.assertIn("tool.skill.manage", prompt)

    def test_skill_review_evidence_contains_trajectory_sections(self) -> None:
        runtime = SimpleNamespace(
            repository=_Repository(),
            list_skills=lambda: (
                SimpleNamespace(
                    skill_id="python-development",
                    display_name="Python Development",
                    instruction_text="Use tool.terminal.exec before tool.file.read when editing Python code.",
                ),
            ),
        )
        job = LearningJob(
            job_id="job-skill-review",
            job_type="episode_boundary_learning",
            trigger="skill_review",
            status="queued",
            personal_model_id="pm",
            state_id="state",
            episode_id="episode",
        )

        evidence = build_evidence(runtime, job, resolve_features("skill_review"))

        self.assertIn("## Trajectory Signals", evidence)
        self.assertIn("## Optimization Candidates", evidence)
        self.assertIn("tool.terminal.exec -> tool.file.read", evidence)


if __name__ == "__main__":
    unittest.main()
