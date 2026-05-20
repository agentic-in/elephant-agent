from __future__ import annotations

import unittest
from types import SimpleNamespace

from apps.reflect.evidence import build_evidence
from apps.reflect.features import resolve_features
from apps.reflect.runner import _assemble_system_prompt, _compose_tools
from packages.contracts.runtime import LearningJob


class DreamFeatureTest(unittest.TestCase):
    def test_dream_trigger_resolves_to_single_nightly_bundle(self) -> None:
        features = resolve_features("dream")

        self.assertEqual(tuple(feature.feature_id for feature in features), ("dream", "questions", "skills", "diary"))

    def test_explicit_dream_drops_pm_learning_but_preserves_questions(self) -> None:
        features = resolve_features("manual", explicit_features=("pm", "questions", "dream", "recall"))

        self.assertEqual(tuple(feature.feature_id for feature in features), ("dream", "questions"))

    def test_dream_trigger_with_legacy_explicit_metadata_adds_nightly_bundle(self) -> None:
        features = resolve_features("dream", explicit_features=("dream", "questions"))

        self.assertEqual(tuple(feature.feature_id for feature in features), ("dream", "questions", "skills", "diary"))

    def test_explicit_dream_alone_stays_dream_only(self) -> None:
        features = resolve_features("manual", explicit_features=("dream",))

        self.assertEqual(tuple(feature.feature_id for feature in features), ("dream",))

    def test_episode_close_resolves_to_pm_questions_and_skills_without_conversation_search(self) -> None:
        features = resolve_features("episode_close")

        self.assertEqual(tuple(feature.feature_id for feature in features), ("pm", "questions", "skills"))
        self.assertNotIn("tool.conversation.search", _compose_tools(features))

    def test_init_profile_resolves_with_link_tools_and_uses_bootstrap_prompt_rules(self) -> None:
        features = resolve_features("init_profile")

        self.assertEqual(tuple(feature.feature_id for feature in features), ("pm", "questions", "skills", "init_links"))

        prompt = _assemble_system_prompt(features, conservatism="low")

        self.assertIn("seed the first question bank more actively", prompt)
        self.assertIn("create 3-6 high-value questions", prompt)
        self.assertIn("explicit init answers and bootstrapped", prompt)
        self.assertIn("tool.web.extract", prompt)
        self.assertIn("tool.browser.navigate", prompt)
        self.assertIn("If the init evidence contains public links", prompt)
        self.assertNotIn("tool.diary.write", prompt)

    def test_init_profile_alias_from_macos_resolves_to_link_learning_bundle(self) -> None:
        features = resolve_features("init", explicit_features=("profile",))

        self.assertEqual(tuple(feature.feature_id for feature in features), ("pm", "questions", "skills", "init_links"))
        self.assertIn("tool.web.read", _compose_tools(features))
        self.assertIn("tool.browser.snapshot", _compose_tools(features))

    def test_init_profile_evidence_omits_empty_episode_and_diary_sections(self) -> None:
        class Repository:
            def load_episode(self, episode_id: str) -> SimpleNamespace:
                return SimpleNamespace(exit_summary="")

            def list_personal_model_facts(self, **_: object) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        lens="identity",
                        text="用户喜欢技术创造。\nRemember: linkedin: https://www.linkedin.com/in/example",
                        metadata={"topic": "identity.style.hobbies.personal"},
                    ),
                )

        runtime = SimpleNamespace(repository=Repository())
        job = LearningJob(
            job_id="job-init",
            job_type="episode_boundary_learning",
            trigger="init_profile",
            status="queued",
            personal_model_id="pm",
            state_id="state",
            episode_id="episode",
            metadata={
                "init_first_language": "zh",
                "init_learning_intensity": "high",
                "init_hobbies": "技术/创造",
                "init_blog": "https://example.com/blog",
            },
        )

        evidence = build_evidence(runtime, job, resolve_features("init_profile"))

        self.assertIn("## Init profile answers", evidence)
        self.assertIn("- learning_intensity: high", evidence)
        self.assertIn("## User-provided links", evidence)
        self.assertIn("- https://example.com/blog", evidence)
        self.assertIn("- https://www.linkedin.com/in/example", evidence)
        self.assertIn("## Bootstrapped Personal Model facts", evidence)
        self.assertIn("[identity] 用户喜欢技术创造。", evidence)
        self.assertNotIn("## Episode summary", evidence)
        self.assertNotIn("## Conversation turns", evidence)
        self.assertNotIn("## Diary context", evidence)

    def test_dream_prompt_requires_pm_consolidation_and_concise_claims(self) -> None:
        features = resolve_features("dream")

        prompt = _assemble_system_prompt(features, conservatism="medium")

        self.assertIn("Dream is a nightly consolidation pass", prompt)
        self.assertIn("expr=<target_date>", prompt)
        self.assertNotIn("expr=today", prompt)
        self.assertIn("tool.personal_model.search mode=inventory status=all", prompt)
        self.assertIn("tool.skill.list", prompt)
        self.assertIn("tool.diary.write", prompt)
        self.assertIn("pruning unreasonable facts", prompt)
        self.assertIn("deduplicating, merging overlapping claims", prompt)
        self.assertIn("CLAIM TEXT RULE", prompt)
        self.assertIn("short, clear, explicit, and unambiguous", prompt)

    def test_dream_evidence_omits_episode_close_packet_when_questions_are_present(self) -> None:
        class Repository:
            def load_episode(self, episode_id: str) -> SimpleNamespace:
                return SimpleNamespace(exit_summary="episode close summary should not appear")

            def list_personal_model_facts(self, **_: object) -> tuple[object, ...]:
                return ()

        runtime = SimpleNamespace(
            repository=Repository(),
            inspect_user=lambda session_id: SimpleNamespace(timezone="Asia/Shanghai"),
        )
        job = LearningJob(
            job_id="job-dream",
            job_type="episode_boundary_learning",
            trigger="dream",
            status="queued",
            personal_model_id="pm",
            state_id="state",
            episode_id="episode",
            metadata={"target_date": "2026-05-14", "diary_target_date": "2026-05-13"},
        )

        evidence = build_evidence(runtime, job, resolve_features("dream"))

        self.assertIn("## Dream context", evidence)
        self.assertIn("target_date: 2026-05-14", evidence)
        self.assertIn("## Diary context", evidence)
        self.assertIn("target_date: 2026-05-13", evidence)
        self.assertNotIn("## Episode summary", evidence)
        self.assertNotIn("## Conversation turns", evidence)
        self.assertNotIn("episode close summary should not appear", evidence)


if __name__ == "__main__":
    unittest.main()
