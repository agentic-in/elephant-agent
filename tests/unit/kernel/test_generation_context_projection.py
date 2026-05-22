"""Unit tests for kernel.generation_context Personal Model projection.

The prompt-contract rewrite (May 2026) replaced the old framework-speak
labels (``State: id=...`` and ``PersonalModelBehavior:``) with prose bullets
and routes durable prompt truth through committed Personal Model facts.

These tests pin that contract directly without the full CliRuntime
harness so regressions fail fast.
"""

from __future__ import annotations

from typing import Any
import unittest

from packages.contracts.runtime import ContextBundle, PromptEnvelope
from packages.kernel.generation_context import build_context_for_generation
from packages.kernel.runtime_support import _apply_execution_guidance
from packages.kernel.runtime_support import KernelSourceRequest


class _FakeStorage:
    """Minimal storage stand-in exposing just what generation_context reads."""

    def __init__(
        self,
        *,
        personal_model: Any = None,
        state: Any = None,
        records: tuple[Any, ...] = (),
        facts: tuple[Any, ...] = (),
        profile: Any = None,
        questions: tuple[Any, ...] = (),
        episode: Any = None,
    ) -> None:
        self._personal_model = personal_model
        self._state = state
        self._records = records
        self._facts = facts
        self._profile = profile
        self._questions = questions
        self._episode = episode

    def load_personal_model(self, _pm_id: str) -> Any:
        return self._personal_model

    def load_state(self, _state_id: str) -> Any:
        return self._state

    def load_episode(self, _episode_id: str) -> Any:
        return self._episode

    def list_records(self, **kwargs: Any) -> tuple[Any, ...]:
        return self._records

    def list_personal_model_facts(self, *, personal_model_id: str, status: str = "active") -> tuple[Any, ...]:
        del personal_model_id, status
        return self._facts

    def load_profile(self, _pm_id: str) -> Any:
        return self._profile

    def list_open_questions(self, *, personal_model_id: str, status: str = "open", limit: int = 6) -> tuple[Any, ...]:
        del personal_model_id, status, limit
        return self._questions


class _FakeDependencies:
    def __init__(self, storage: _FakeStorage) -> None:
        self.storage = storage
        self.context = _FakeContextDep()


class _FakeContextDep:
    # No augment_for_generation — generation_context handles that branch.
    pass


class _FakeRequest:
    def __init__(
        self,
        *,
        personal_model_id: str = "pm:1",
        state_id: str = "state:1",
        surface: str = "cli",
        source_payload: dict[str, str] | None = None,
    ) -> None:
        self.personal_model_id = personal_model_id
        self.state_id = state_id
        self.tool_name = None
        self.surface = surface
        self.source_event_type = "turn.received"
        self.source_payload = source_payload or {}


def _bundle() -> ContextBundle:
    envelope = PromptEnvelope(
        frozen_prefix="",
        session_snapshot="",
        loop_context="",
        messages=(),
    )
    return ContextBundle(
        bundle_id="bundle:test",
        episode_id="episode:test",
        rendered_prompt="",
        prompt_envelope=envelope,
    )


def _fact(*, text: str, field: str, lens: str = "knowledge", confidence: float = 1.0, extra_metadata: dict[str, str] | None = None) -> Any:
    topic_by_field = {
        "identity.name.preferred": "identity.anchor.name.preferred",
        "city": "world.places.city.current",
        "first_language": "identity.style.language.first",
        "pressure_pattern": "identity.character.rhythm.pressure",
        "recovery_style": "identity.character.rhythm.recovery",
        "decision_compass": "identity.character.decision.compass",
    }
    return type(
        "_Fact",
        (),
        {
            "text": text,
            "lens": lens,
            "confidence": confidence,
            "metadata": {"field": field, "topic": topic_by_field.get(field, field), "protected": "system", "projection_policy": "core_prompt", **(extra_metadata or {})},
        },
    )()


def _profile(*, preferences: tuple[str, ...] = (), user_profile_text: str = "", style_summary: str = "") -> Any:
    return type(
        "_Profile",
        (),
        {
            "preferences": preferences,
            "user_profile_text": user_profile_text,
            "style_summary": style_summary,
        },
    )()


def _question(*, text: str = "When things get messy, what helps?", sub_lens: str = "stress_response") -> Any:
    return type(
        "_Question",
        (),
        {
            "question_id": "oq:1",
            "lens": "trait",
            "sub_lens": sub_lens,
            "text": text,
            "rationale": "coverage gap",
            "priority": 0.5,
            "sensitivity": "low",
            "source": "coverage_gap",
            "metadata": {"seed_text": text},
        },
    )()


class GenerationContextProjectionTest(unittest.TestCase):
    def test_learning_agent_context_mode_gets_minimal_generation_context(self) -> None:
        context = ContextBundle(
            bundle_id="bundle:test",
            episode_id="episode:test",
            rendered_prompt="SHOULD NOT SURFACE",
            prompt_envelope=PromptEnvelope(
                frozen_prefix="### What I know so far\n- private user prompt fact",
                session_snapshot="Episode resume: private",
                loop_context="Current-turn recall: private",
                messages=("old message",),
            ),
            instruction_refs=("instruction:1",),
            evidence_refs=("evidence:1",),
            artifact_ids=("artifact:1",),
            work_item_ids=("work:1",),
        )

        result = build_context_for_generation(
            dependencies=_FakeDependencies(_FakeStorage()),
            request=_FakeRequest(source_payload={"context_mode": "learning_agent"}),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=context,
            decision=None,
            plan=None,
            continuity=None,
        )

        self.assertEqual(result.rendered_prompt, "")
        self.assertEqual(result.prompt_envelope, PromptEnvelope())
        self.assertEqual(result.instruction_refs, ())
        self.assertEqual(result.work_item_ids, ())
        self.assertEqual(result.evidence_refs, ())
        self.assertEqual(result.artifact_ids, ())

    def test_learning_agent_minimal_context_can_carry_dedicated_system_prompt(self) -> None:
        result = build_context_for_generation(
            dependencies=_FakeDependencies(_FakeStorage()),
            request=_FakeRequest(source_payload={"context_mode": "learning_agent", "system_prompt": "SYSTEM ONLY"}),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=_bundle(),
            decision=None,
            plan=None,
            continuity=None,
        )

        self.assertEqual(result.prompt_envelope.frozen_prefix, "SYSTEM ONLY")
        self.assertEqual(result.prompt_envelope.loop_context, "")
        self.assertEqual(result.rendered_prompt, "SYSTEM ONLY")

    def test_learning_agent_prompt_is_not_modified_by_runtime(self) -> None:
        """Learning agent prompts bypass execution guidance via _prompt_for_request_execution,
        which checks source_event_type='turn.internal'. Here we verify that a prompt
        without multi-source/compare markers passes through _apply_execution_guidance unchanged."""
        prompt = "Mode: manual\nReview active PM facts."

        result = _apply_execution_guidance(prompt)

        self.assertEqual(result, prompt)
        self.assertNotIn("Execution guidance for this turn", result)

    def test_regular_prompt_still_gets_global_execution_guidance(self) -> None:
        request = KernelSourceRequest(
            route_id="episode:foreground",
            prompt="Compare the latest current approaches for PM maintenance.",
        )

        prompt = _apply_execution_guidance(request.prompt)

        self.assertIn("Execution guidance for this turn", prompt)
        self.assertIn("tool.web.search", prompt)

    def test_core_prompt_filters_internal_learning_artifact_facts(self) -> None:
        result = build_context_for_generation(
            dependencies=_FakeDependencies(
                _FakeStorage(
                    facts=(
                        _fact(text="Question-bank signal for feedback_preference: explicit", field="question.signal", lens="rapport"),
                        _fact(text="User explicitly shared autonomy_boundary: 的心事更在前面？", field="question.noise", lens="rapport"),
                        _fact(
                            text="Synthetic live acceptance marker for init_bootstrap mode validation. run_tag=20260509135158.",
                            field="validation.marker",
                            lens="knowledge",
                            extra_metadata={"recall_policy": "temporary"},
                        ),
                        _fact(text="第一语言：中文。", field="first_language", lens="rapport"),
                    )
                )
            ),
            request=_FakeRequest(),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=_bundle(),
            decision=None,
            plan=None,
            continuity=None,
        )

        prompt = result.prompt_envelope.frozen_prefix
        self.assertIn("第一语言：中文", prompt)
        self.assertNotIn("Question-bank signal", prompt)
        self.assertNotIn("User explicitly shared autonomy_boundary", prompt)
        self.assertNotIn("Synthetic live acceptance marker", prompt)

    def test_core_prompt_filters_skill_optimization_review_candidates(self) -> None:
        result = build_context_for_generation(
            dependencies=_FakeDependencies(
                _FakeStorage(
                    facts=(
                        _fact(text="第一语言：中文。", field="first_language", lens="rapport"),
                        _fact(
                            text="python-development shows a repeatable optimization opportunity.",
                            field="world.skills.optimization.python_development.update_procedure_ab12cd34",
                            lens="world",
                            extra_metadata={
                                "topic": "world.skills.optimization.python_development.update_procedure_ab12cd34",
                                "recall_policy": "review",
                                "retention_lifecycle": "draft",
                                "projection_policy": "skill_optimization_candidate",
                            },
                        ),
                    )
                )
            ),
            request=_FakeRequest(),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=_bundle(),
            decision=None,
            plan=None,
            continuity=None,
        )

        prompt = result.prompt_envelope.frozen_prefix
        self.assertIn("第一语言：中文", prompt)
        self.assertNotIn("repeatable optimization opportunity", prompt)
        self.assertNotIn("world.skills.optimization", prompt)

    def test_gateway_state_projection_does_not_inject_previous_assistant_reply_as_ongoing_thread(self) -> None:
        state = type(
            "_State",
            (),
            {
                "summary": "xunzhuo，中午好呀。你是想倒倒苦水，还是就想有人知道你今天很忙？",
                "current_context_note": "xunzhuo，中午好呀。你是想倒倒苦水，还是就想有人知道你今天很忙？",
                "active_task": "你好呀",
                "next_step": "",
                "blockers": (),
            },
        )()
        storage = _FakeStorage(state=state)

        result = build_context_for_generation(
            dependencies=_FakeDependencies(storage),
            request=_FakeRequest(surface="gateway:messaging.weixin"),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=_bundle(),
            decision=None,
            plan=None,
            continuity=None,
        )

        rendered = result.rendered_prompt or ""
        self.assertNotIn("Ongoing thread:", rendered)
        self.assertNotIn("Active task: 你好呀", rendered)

    def test_episode_resume_snapshot_stays_out_of_frozen_prefix(self) -> None:
        episode = type(
            "_Episode",
            (),
            {
                "metadata": {
                    "opening_resume_snapshot": "Use the live project handoff as the current Elephant context."
                }
            },
        )()
        result = build_context_for_generation(
            dependencies=_FakeDependencies(_FakeStorage(episode=episode)),
            request=_FakeRequest(surface="cli"),
            profile=None,
            session=type("_Session", (), {"episode_id": "episode:test"})(),
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=_bundle(),
            decision=None,
            plan=None,
            continuity=None,
        )

        envelope = result.prompt_envelope
        self.assertIn("Use the live project handoff", envelope.frozen_prefix)
        self.assertIn("### Episode resume", envelope.frozen_prefix)
        self.assertIn("Resume note: Use the live project handoff", envelope.frozen_prefix)

    def test_token_budget_is_not_injected_into_system_prompt(self) -> None:
        context = ContextBundle(
            bundle_id="bundle:test",
            episode_id="episode:test",
            rendered_prompt="",
            token_budget=204800,
            prompt_envelope=PromptEnvelope(
                frozen_prefix="### Who you are\n- You are Jasper.",
                session_snapshot="",
                loop_context="",
                messages=(),
            ),
        )
        result = build_context_for_generation(
            dependencies=_FakeDependencies(_FakeStorage(facts=(_fact(text="称呼：xunzhuo。", field="identity.name.preferred"),))),
            request=_FakeRequest(),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=context,
            decision=None,
            plan=None,
            continuity=None,
        )

        prompt = result.prompt_envelope.frozen_prefix
        rendered = result.rendered_prompt or ""
        self.assertNotIn("Prompt budget", prompt)
        self.assertNotIn("204800", prompt)
        self.assertNotIn("Prompt budget", rendered)
        self.assertNotIn("204800", rendered)

    def test_pm_facts_replace_raw_user_snapshot_and_skill_index_moves_late(self) -> None:
        skill_block = "\n".join(
            (
                "### Capability Disclosure",
                "Skill index is discovery-only.",
                "Skill index (1 runtime-eligible prompt-visible entries):",
                "- runtime - Web Search (web-search)",
            )
        )
        context = ContextBundle(
            bundle_id="bundle:test",
            episode_id="episode:test",
            rendered_prompt="",
            prompt_envelope=PromptEnvelope(
                frozen_prefix="\n\n".join(
                    (
                        "### Who you are\n- You are Jasper.",
                        "### What you know about the user\n- Preferred name: xunzhuo\n- Current city: 成都",
                        "### Your own voice\nSteady and grounded.",
                        skill_block,
                    )
                ),
                session_snapshot="",
                loop_context="",
                messages=(),
            ),
        )
        storage = _FakeStorage(
            facts=(
                _fact(text="称呼：xunzhuo。", field="identity.name.preferred", lens="knowledge"),
                _fact(text="城市或时区语境：成都。", field="city", lens="knowledge"),
            ),
            profile=_profile(preferences=("first_language=zh",)),
        )

        result = build_context_for_generation(
            dependencies=_FakeDependencies(storage),
            request=_FakeRequest(),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=context,
            decision=None,
            plan=None,
            continuity=None,
        )

        prompt = result.prompt_envelope.frozen_prefix
        self.assertNotIn("### What you know about the user", prompt)
        self.assertIn("### What I know so far", prompt)
        self.assertIn("### Identity — who they are", prompt)
        self.assertIn("### World — what is around them", prompt)
        self.assertIn("称呼：xunzhuo", prompt)
        self.assertIn("城市或时区语境：成都", prompt)
        self.assertLess(prompt.index("### Identity — who they are"), prompt.index("### Capability Disclosure"))

    def test_pm_facts_replace_stale_frozen_personal_projection(self) -> None:
        context = ContextBundle(
            bundle_id="bundle:test",
            episode_id="episode:test",
            rendered_prompt="",
            prompt_envelope=PromptEnvelope(
                frozen_prefix="\n\n".join(
                    (
                        "### Who you are\n- You are Jasper.",
                        "### What I know so far\n### Their world\n- Preferred name: stale",
                        "### Your own voice\nSteady and grounded.",
                    )
                ),
                session_snapshot="",
                loop_context="",
                messages=(),
            ),
        )
        result = build_context_for_generation(
            dependencies=_FakeDependencies(
                _FakeStorage(facts=(_fact(text="称呼：zoey。", field="identity.name.preferred", lens="knowledge"),))
            ),
            request=_FakeRequest(),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=context,
            decision=None,
            plan=None,
            continuity=None,
        )

        prompt = result.prompt_envelope.frozen_prefix
        self.assertIn("称呼：zoey", prompt)
        self.assertNotIn("Preferred name: stale", prompt)

    def test_style_guidance_is_behavioral_not_raw_database_summary(self) -> None:
        storage = _FakeStorage(
            facts=(
                _fact(text="压力升起来时，常见反应是：先安静下来。", field="pressure_pattern", lens="trait"),
                _fact(text="恢复精力时，较早有用的是：安静一会儿。", field="recovery_style", lens="trait"),
                _fact(text="面对悬而未决的选择时，更靠近答案的方式是：写下取舍。", field="decision_compass", lens="trait"),
            ),
            profile=_profile(
                preferences=("relationship_mode=安静、细腻、低压地陪在旁边",),
                style_summary="trait: moves toward decisions through: 写下取舍; recovers first through: 安静一会儿.",
            ),
        )
        result = build_context_for_generation(
            dependencies=_FakeDependencies(storage),
            request=_FakeRequest(),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=_bundle(),
            decision=None,
            plan=None,
            continuity=None,
        )

        prompt = result.prompt_envelope.frozen_prefix
        self.assertIn("### Identity — who they are", prompt)
        self.assertIn("压力升起来时", prompt)
        self.assertIn("恢复精力时", prompt)
        self.assertIn("面对悬而未决的选择", prompt)
        self.assertNotIn("Style summary: trait:", prompt)

    def test_curiosity_hint_routes_question_selection_through_tool(self) -> None:
        storage = _FakeStorage(
            facts=(
                _fact(text="第一语言：中文；除非用户另行要求，默认使用中文沟通。", field="first_language", lens="rapport"),
                _fact(text="称呼：xunzhuo。", field="identity.name.preferred", lens="knowledge"),
            ),
            profile=_profile(),
            questions=(
                _question(text="when things get messy, do you want a checklist first?"),
                _question(text="when your energy is low, do you need quiet space first?", sub_lens="energy_management"),
            ),
        )
        result = build_context_for_generation(
            dependencies=_FakeDependencies(storage),
            request=_FakeRequest(),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=_bundle(),
            decision=None,
            plan=None,
            continuity=None,
        )

        loop_context = result.prompt_envelope.loop_context
        self.assertNotIn("### Personal Model questions to ask only if useful", loop_context)
        self.assertNotIn("tool.personal_model.questions", loop_context)
        self.assertNotIn("when things get messy", loop_context)
        self.assertNotIn("- (low)", loop_context)

    def test_placeholder_user_names_are_suppressed(self) -> None:
        """Historic bug: `elephant herd new` wrote the suggested *elephant* name
        (Hazel, Zoey, Leah, ...) into the *personal_model* row. Prompt
        then read `Person on the other side: Hazel` before the user
        ever said their name. Render-time filter catches it until a
        real name arrives via `tool.personal_model.update`.
        """
        class _PersonalModel:
            display_name = "Hazel"
            status = "active"

        class _State:
            state_id = "state:1"
            elephant_name = "Zoey"
            elephant_id = "zoey"
            state_anchor = "elephant:zoey"
            summary = ""
            active_task = ""
            next_step = ""
            posture = ""
            initiative = ""
            working_style = ""
            blockers: tuple[str, ...] = ()

        class _StorageWithPersonalModel(_FakeStorage):
            def load_personal_model(self, _pm_id: str) -> object:
                return _PersonalModel()

            def load_state(self, _state_id: str) -> object:
                return _State()

        dependencies = _FakeDependencies(_StorageWithPersonalModel())
        result = build_context_for_generation(
            dependencies=dependencies,
            request=_FakeRequest(),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=_bundle(),
            decision=None,
            plan=None,
            continuity=None,
        )

        rendered = result.rendered_prompt or ""
        # The placeholder user name must not surface.
        self.assertNotIn("Person on the other side: Hazel", rendered)
        # Companion name is carried by the canonical Who you are section, not
        # repeated under Where things stand.
        self.assertNotIn("You are showing up as Zoey in this session.", rendered)

    def test_reflexive_display_name_is_suppressed(self) -> None:
        """When display_name decayed to a reflexive pronoun like "You",
        we must not emit "You are You" absurdity.
        """
        class _PersonalModel:
            display_name = "You"
            status = "active"

        class _StorageWithPersonalModel(_FakeStorage):
            def load_personal_model(self, _pm_id: str) -> object:
                return _PersonalModel()

        dependencies = _FakeDependencies(_StorageWithPersonalModel())
        result = build_context_for_generation(
            dependencies=dependencies,
            request=_FakeRequest(),
            profile=None,
            session=None,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=_bundle(),
            decision=None,
            plan=None,
            continuity=None,
        )

        rendered = result.rendered_prompt or ""
        self.assertNotIn("Person on the other side: You", rendered)


if __name__ == "__main__":
    unittest.main()
