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

        self.assertEqual(
            tuple(feature.feature_id for feature in features),
            ("dream", "questions", "skills", "skill_optimization", "diary"),
        )

    def test_explicit_dream_drops_pm_learning_but_preserves_questions(self) -> None:
        features = resolve_features("manual", explicit_features=("pm", "questions", "dream", "recall"))

        self.assertEqual(tuple(feature.feature_id for feature in features), ("dream", "questions"))

    def test_dream_trigger_with_legacy_explicit_metadata_adds_nightly_bundle(self) -> None:
        features = resolve_features("dream", explicit_features=("dream", "questions"))

        self.assertEqual(
            tuple(feature.feature_id for feature in features),
            ("dream", "questions", "skills", "skill_optimization", "diary"),
        )

    def test_explicit_dream_alone_stays_dream_only(self) -> None:
        features = resolve_features("manual", explicit_features=("dream",))

        self.assertEqual(tuple(feature.feature_id for feature in features), ("dream",))

    def test_episode_close_resolves_to_pm_questions_and_skills_without_conversation_search(self) -> None:
        features = resolve_features("episode_close")

        self.assertEqual(tuple(feature.feature_id for feature in features), ("pm", "questions", "skills"))
        self.assertNotIn("tool.conversation.search", _compose_tools(features))

    def test_init_profile_resolves_with_link_tools_and_uses_bootstrap_prompt_rules(self) -> None:
        features = resolve_features("init_profile")

        self.assertEqual(tuple(feature.feature_id for feature in features), ("init_links", "pm", "questions", "skills"))

        prompt = _assemble_system_prompt(features, conservatism="low")

        self.assertIn("## Init Profile Orchestration", prompt)
        self.assertIn("Run order overrides feature listing", prompt)
        self.assertIn("inspect each user-provided URL", prompt)
        self.assertIn("before writing link-derived claims", prompt)
        self.assertIn("seed the first question bank more actively", prompt)
        self.assertIn("create 3-6 high-value questions", prompt)
        self.assertIn("explicit init answers and bootstrapped", prompt)
        self.assertIn("tool.web.extract", prompt)
        self.assertIn("tool.browser.navigate", prompt)
        self.assertIn("first-profile construction", prompt)
        self.assertIn("PM search only checks existing claims", prompt)
        self.assertIn("PM search cannot open URLs", prompt)
        self.assertNotIn("tool.diary.write", prompt)

    def test_onboarding_letter_prompt_writes_diary_metadata(self) -> None:
        features = resolve_features("onboarding_letter")

        self.assertEqual(tuple(feature.feature_id for feature in features), ("onboarding_letter",))
        self.assertIn("tool.diary.write", _compose_tools(features))
        self.assertNotIn("tool.diary.list", _compose_tools(features))
        self.assertNotIn("tool.personal_model.search", _compose_tools(features))

        prompt = _assemble_system_prompt(features, conservatism="creative")

        self.assertIn("writing your first letter to the user", prompt)
        self.assertIn("small elephant", prompt)
        self.assertIn("metadata={\"kind\":\"onboarding_letter\"", prompt)
        self.assertIn("call tool.diary.write exactly once", prompt)
        self.assertIn("Never say or imply \"I am not Elephant\"", prompt)
        self.assertIn("This letter is only the body text", prompt)
        self.assertIn("Do not write a title or repeat the UI title", prompt)
        self.assertIn("psychological, sociological, and philosophical depth", prompt)
        self.assertIn("work-world, the tension being carried", prompt)
        self.assertIn("Wang Xiaobo", prompt)
        self.assertIn("John Keats", prompt)
        self.assertIn("localized to the letter language", prompt)
        self.assertIn("别怕，我们一同进化", prompt)
        self.assertIn("Don't be afraid; we evolve together", prompt)
        self.assertIn("Do not put the Chinese phrase in a non-Chinese letter", prompt)
        self.assertIn("Use letter-like markdown formatting", prompt)
        self.assertIn("Do not mention literal phrases such as \"技能匹配\"", prompt)
        self.assertNotIn("Active features:", prompt)
        self.assertNotIn("Allowed tools:", prompt)
        self.assertNotIn("## SOP", prompt)
        self.assertNotIn("tool.diary.list", prompt)
        self.assertNotIn("tool.personal_model.search", prompt)
        self.assertNotIn("CLAIM TEXT RULE", prompt)
        self.assertNotIn("tool.personal_model.update call MUST", prompt)
        self.assertNotIn("Never store system artifacts as PM facts", prompt)

    def test_init_profile_alias_from_macos_resolves_to_link_learning_bundle(self) -> None:
        features = resolve_features("init", explicit_features=("profile",))

        self.assertEqual(tuple(feature.feature_id for feature in features), ("init_links", "pm", "questions", "skills"))
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
        self.assertIn("## Init learning objective", evidence)
        self.assertIn("## Init Evidence Use", evidence)
        self.assertIn("PM search is for inventory and deduplication only", evidence)
        self.assertIn("User-provided links are present", evidence)
        self.assertIn("- learning_intensity: high", evidence)
        self.assertIn("## User-provided links", evidence)
        self.assertIn("- https://example.com/blog", evidence)
        self.assertIn("- https://www.linkedin.com/in/example", evidence)
        self.assertIn("## Bootstrapped Personal Model facts", evidence)
        self.assertIn("[identity] 用户喜欢技术创造。", evidence)
        self.assertNotIn("## Episode summary", evidence)
        self.assertNotIn("## Conversation turns", evidence)
        self.assertNotIn("## Diary context", evidence)

    def test_init_profile_evidence_recovers_seed_answers_and_bare_links(self) -> None:
        class Repository:
            def load_episode(self, episode_id: str) -> SimpleNamespace:
                return SimpleNamespace(exit_summary="")

            def list_personal_model_facts(self, **_: object) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        lens="identity",
                        text="训灼",
                        metadata={"topic": "identity.anchor.name.preferred", "init_profile_field": "preferred_name"},
                    ),
                    SimpleNamespace(
                        lens="world",
                        text="blog: liuxunzhuo.com",
                        metadata={"topic": "world.links.blog", "init_profile_field": "blog"},
                    ),
                    SimpleNamespace(
                        lens="identity",
                        text="personal_logo: /tmp/user-avatar.jpg",
                        metadata={"topic": "identity.anchor.logo.personal", "init_profile_field": "personal_logo"},
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
            metadata={},
        )

        evidence = build_evidence(runtime, job, resolve_features("init_profile"))

        self.assertIn("- preferred_name: 训灼", evidence)
        self.assertIn("- blog: liuxunzhuo.com", evidence)
        self.assertIn("- https://liuxunzhuo.com", evidence)
        self.assertNotIn("user-avatar.jpg", evidence)
        self.assertIn("User-provided links are present", evidence)

    def test_onboarding_letter_evidence_uses_full_pm_portrait(self) -> None:
        class Repository:
            def load_episode(self, episode_id: str) -> SimpleNamespace:
                return SimpleNamespace(exit_summary="")

            def list_personal_model_facts(self, **_: object) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        lens="world",
                        text="用户正在做工程方向的 AI 产品。",
                        metadata={"topic": "world.projects.ai_product.current"},
                    ),
                    SimpleNamespace(
                        lens="identity",
                        text="用户压力大时需要先安静下来。",
                        metadata={"topic": "identity.character.recovery.quiet"},
                    ),
                    SimpleNamespace(
                        lens="identity",
                        text="personal_logo: /tmp/user-avatar.jpg",
                        metadata={"topic": "identity.anchor.logo.personal"},
                    ),
                    SimpleNamespace(
                        lens="world",
                        text="blog: liuxunzhuo.com",
                        metadata={"topic": "world.links.blog"},
                    ),
                    SimpleNamespace(
                        lens="world",
                        text="用户适合使用 code-review-pro skill。",
                        metadata={"topic": "world.skills.affinity.code_review"},
                    ),
                )

        runtime = SimpleNamespace(
            repository=Repository(),
            inspect_user=lambda session_id: SimpleNamespace(timezone="Asia/Shanghai"),
        )
        job = LearningJob(
            job_id="job-letter",
            job_type="episode_boundary_learning",
            trigger="onboarding_letter",
            status="queued",
            personal_model_id="pm",
            state_id="state",
            episode_id="episode",
            metadata={"target_date": "2026-05-23"},
        )

        evidence = build_evidence(runtime, job, resolve_features("onboarding_letter"))

        self.assertIn("target_date: 2026-05-23", evidence)
        self.assertIn("letter_kind: onboarding_letter", evidence)
        self.assertIn("## Personal Model facts", evidence)
        self.assertIn("All active facts available after onboarding and initial learning", evidence)
        self.assertIn("[world] 用户正在做工程方向的 AI 产品。", evidence)
        self.assertIn("[identity] 用户压力大时需要先安静下来。", evidence)
        self.assertIn("[world] 用户适合使用 code-review-pro skill。", evidence)
        self.assertNotIn("user-avatar.jpg", evidence)
        self.assertIn("blog: liuxunzhuo.com", evidence)
        self.assertIn("skill matching", evidence)
        self.assertIn("技能匹配", evidence)
        self.assertIn("replaced, accelerated, or flattened", evidence)
        self.assertIn("别怕，我们一同进化", evidence)
        self.assertIn("Don't be afraid; we evolve together", evidence)
        self.assertIn("Do not use the Chinese phrase in a non-Chinese letter", evidence)
        self.assertIn("evolve with the user", evidence)
        self.assertNotIn("trigger: onboarding_letter", evidence)
        self.assertNotIn("features: onboarding_letter", evidence)
        self.assertNotIn("## User anchors", evidence)

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
