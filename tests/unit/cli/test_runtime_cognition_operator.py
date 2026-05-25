# ruff: noqa: E402

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.cli.runtime import CliRuntime, _CliContextCapability, _DurableRecallCapability
from apps.cli.runtime_snapshot import load_snapshot_session_context_epoch, restore_snapshot_state_focus
from packages.contracts import (
    ContextBundle,
    Episode,
    EventEnvelope,
    ExecutionResult,
    Fact,
    Loop,
    PersonalModelGrowthState,
    PromptEnvelope,
    PromptMessage,
    Step,
)
from packages.contracts.runtime import (
    EmbeddingIndexPolicy,
    EvidenceRetrievalRequest,
    EvidenceRetrievalResult,
    LoopState,
    RecallEvidence,
    RecallReasons,
    StateFocusDecision,
)
from packages.state import render_user_profile_text
from packages.state.loader import write_profile_manifest
from packages.state.persistence import load_persisted_canonical_state
from packages.skills import (
    FetchedSkillBundle,
    SkillSearchEntry,
    builtin_site_skill_catalog_entries,
    operator_prompt_skill_catalog_entries,
)
from tests.unit.cli.runtime_cognition_test_base import RuntimeCognitionTestBase


class CliRuntimeCognitionOperatorTest(RuntimeCognitionTestBase):
    def test_operator_profile_surface_can_inspect_and_update_profile_surface(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        inspected_profile = runtime.inspect_profile_surface(session.episode_id)
        updated_profile = runtime.patch_profile_surface(
            session.episode_id,
            {
                "display_name": "Atlas",
                "personality_preset": "operator",
                "initiative": "proactive",
                "elephant_identity_text": "Stay concise, direct, and durable for Atlas.",
                "user_fields": {
                    "preferred_name": "xunzhuo",
                    "current_work": "Software engineer",
                },
                "user_text": "Prefers direct updates and wants long-horizon context preserved.",
                "relationship_text": "Keep responses concise and grounded.",
            },
        )

        self.assertEqual(inspected_profile.identity.display_name, "Atlas")
        self.assertEqual(updated_profile.identity.display_name, "Atlas")
        self.assertEqual(updated_profile.identity.personality_preset, "operator")
        self.assertEqual(updated_profile.identity.initiative, "proactive")
        self.assertEqual(updated_profile.user.preferred_name, "xunzhuo")
        self.assertIn("Prefers direct updates and wants long-horizon context preserved.", updated_profile.user.durable_notes)
        self.assertIn("Keep responses concise and grounded.", updated_profile.relationship.continuity_notes)
        user = runtime.inspect_user(session_id=session.episode_id)
        self.assertIn("current_work:Software engineer", user.biography_fragments)
        self.assertEqual(
            user.durable_notes,
            ("Prefers direct updates and wants long-horizon context preserved.",),
        )

    def test_operator_profile_surface_accepts_scoped_user_fields(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        updated = runtime.patch_profile_surface(
            session.episode_id,
            {
                "user_text": "\n".join(
                    (
                        "Preferred name: xunzhuo",
                        "Current work: Software engineer",
                        "Remember: Prefers direct progress updates.",
                    )
                ),
            },
        )

        self.assertEqual(updated.user.preferred_name, "xunzhuo")
        user = runtime.inspect_user(session_id=session.episode_id)
        self.assertIn("current_work:Software engineer", user.biography_fragments)
        self.assertEqual(user.durable_notes, ("Prefers direct progress updates.",))

    def test_operator_profile_surface_persists_structured_biography_fields_in_profile_summary(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        runtime.patch_profile_surface(
            session.episode_id,
            {
                "user_fields": {
                    "mbti": "INFJ",
                    "assistant_mbti_preference": "ENFP",
                },
            },
        )
        updated = runtime.patch_profile_surface(
            session.episode_id,
            {
                "relationship_append": False,
                "user_append": False,
                "user_fields": {
                    "name": "Xunzhuo",
                    "country_of_origin": "China",
                    "employer": "Tencent",
                },
            },
        )

        self.assertEqual(updated.user.preferred_name, "Xunzhuo")
        for fragment in (
            "country_of_origin:China",
            "employer:Tencent",
            "mbti:INFJ",
            "assistant_mbti_preference:ENFP",
        ):
            self.assertIn(fragment, updated.user.biography_fragments)
        user = runtime.inspect_user(session_id=session.episode_id)
        self.assertEqual(user.preferred_name, "Xunzhuo")
        for fragment in (
            "country_of_origin:China",
            "employer:Tencent",
            "mbti:INFJ",
            "assistant_mbti_preference:ENFP",
        ):
            self.assertIn(fragment, user.biography_fragments)

    def test_operator_profile_surface_can_update_identity_posture(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        updated = runtime.patch_profile_surface(
            session.episode_id,
            {
                "personality_preset": "operator",
                "initiative": "proactive",
            },
        )

        self.assertEqual(updated.identity.personality_preset, "operator")
        self.assertEqual(updated.identity.initiative, "proactive")
        identity = runtime.inspect_identity(session_id=session.episode_id)
        self.assertEqual(identity.personality_preset, "operator")
        self.assertEqual(identity.initiative, "proactive")

    def test_personal_model_update_tool_runtime_uses_refreshed_canonical_state_surface(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        assert runtime.model_provider.tool_runtime is not None
        updated = runtime.model_provider.tool_runtime.invoke(
            "tool.personal_model.update",
            {
                "action": "remember",
                "lens": "pulse",
                "topic": "pulse.chapter.work.role",
                "text": "The user's current work is Software engineer.",
                "reason": "user explicitly stated current work",
            },
            session_id=session.episode_id,
        )

        self.assertEqual(updated.outcome, "success")
        self.assertIn("status: active", updated.summary)
        facts = runtime.repository.list_personal_model_facts(
            personal_model_id=session.personal_model_id,
            status="active",
        )
        self.assertTrue(any("Software engineer" in fact.text for fact in facts))

    def test_profile_persistence_syncs_canonical_owner_records_and_ledgers(self) -> None:
        runtime = self._runtime(
            profile_payload={
                "profile_id": "profile-companion",
                "display_name": "Elephant Agent",
                "mode": "companion",
                "locale": "zh-CN",
                "timezone": "Asia/Shanghai",
            },
            seed_charter=False,
        )
        profile_id = runtime.current_profile().state.profile_id

        runtime.update_identity_state(
            profile_id=profile_id,
            elephant_identity_text="Stay calm, durable, and exact.",
        )
        persisted = load_persisted_canonical_state(runtime.repository, profile_id)
        elephant_identity = persisted.elephant_identity
        user_profile = persisted.user_profile
        relationship = persisted.relationship

        self.assertIsNotNone(elephant_identity)
        self.assertIsNotNone(user_profile)
        self.assertIsNotNone(relationship)
        assert elephant_identity is not None
        assert user_profile is not None
        assert relationship is not None
        self.assertEqual(elephant_identity.elephant_identity_text, "Stay calm, durable, and exact.")
        self.assertIsNotNone(runtime.repository.load_elephant_identity_for_profile(profile_id))
        facts = runtime.repository.list_personal_model_facts(personal_model_id=profile_id, status="active")
        self.assertFalse(any(fact.metadata.get("canonical_component") in {"user-profile", "relationship"} for fact in facts))

        runtime.update_user_state(
            profile_id=profile_id,
            text=render_user_profile_text(
                preferred_name="Bit",
                current_work="Build Elephant Agent",
                boundaries="Prefer direct updates.",
            ),
        )
        persisted = load_persisted_canonical_state(runtime.repository, profile_id)
        user_profile = persisted.user_profile
        relationship = persisted.relationship

        assert user_profile is not None
        assert relationship is not None
        self.assertEqual(user_profile.preferred_name, "Bit")
        self.assertIn("current_work:Build Elephant Agent", user_profile.biography_fragments)

        runtime.update_identity_state(
            profile_id=profile_id,
            personality_preset="operator",
            initiative="proactive",
        )
        persisted = load_persisted_canonical_state(runtime.repository, profile_id)
        elephant_identity = persisted.elephant_identity
        relationship = persisted.relationship

        assert elephant_identity is not None
        assert relationship is not None
        self.assertEqual(elephant_identity.personality_preset, "operator")
        self.assertEqual(elephant_identity.initiative, "proactive")
        self.assertIn("initiative:proactive", relationship.expectations)

    def test_create_elephant_starts_without_legacy_goal_seed(self) -> None:
        runtime = self._runtime()

        session = runtime.create_elephant(elephant_id="atlas")

        elephant_state = runtime.repository.load_state("state:atlas")

        self.assertIsNotNone(elephant_state)
        assert elephant_state is not None
        self.assertEqual(elephant_state.state_id, "state:atlas")

    def test_cli_context_capability_surfaces_active_loop_checkpoint(self) -> None:
        runtime = self._runtime()
        session = runtime.start()
        now = datetime.now(timezone.utc)
        runtime.repository.upsert_loop_checkpoint(
            LoopState(
                run_id=f"loop:{session.episode_id}:pending",
                episode_id=session.episode_id,
                source_event_id="event-old",
                prompt="Audit the long-horizon loop design.",
                status="pending",
                phase="waiting",
                step_count=4,
                model_turn_count=2,
                tool_call_count=2,
                max_model_turns=24,
                max_wall_time_seconds=180,
                created_at=now,
                updated_at=now,
                waiting_reason="model-turn-budget",
                continuation_prompt="Continue the same Elephant Agent loop checkpoint from its durable checkpoint.",
                last_summary="Collected Elephant Agent and OpenClaw reference points.",
            )
        )
        capability = _CliContextCapability(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
            tool_runtime=runtime.tool_runtime,
        )

        bundle = capability.assemble(session, (), ())

        self.assertIn("active-loop-checkpoint:", bundle.rendered_prompt)
        self.assertIn("Audit the long-horizon loop design", bundle.rendered_prompt)
        self.assertIn("Collected Elephant Agent and OpenClaw reference points", bundle.rendered_prompt)

    def test_delete_elephant_clears_sessions_and_memories_for_that_elephant(self) -> None:
        runtime = self._runtime()
        session = runtime.create_elephant(elephant_id="atlas")

        deleted_sessions = runtime.delete_elephant("atlas")

        self.assertEqual(deleted_sessions, 1)
        self.assertIsNone(runtime.repository.load_episode_state(session.episode_id))
        self.assertEqual(runtime.recall_runtime.store.list(session.episode_id, include_inactive=True), ())
        self.assertIsNotNone(runtime.repository.load_personal_model(session.personal_model_id))
        self.assertIsNone(runtime.repository.load_state("state:atlas"))
        self.assertEqual(runtime.list_herd(), ())

    def test_delete_all_elephants_clears_state_rows_and_preserves_personal_model(self) -> None:
        runtime = self._runtime()
        alpha = runtime.create_elephant(elephant_id="alpha")
        beta = runtime.create_elephant(elephant_id="beta")

        deleted_elephants, deleted_sessions = runtime.delete_all_elephants()

        self.assertEqual(deleted_elephants, 2)
        self.assertEqual(deleted_sessions, 2)
        self.assertEqual(runtime.list_herd(), ())
        with runtime.repository.connection() as connection:
            profile_rows = connection.execute(
                """
                SELECT personal_model_id
                FROM personal_models
                WHERE personal_model_id IN (?, ?)
                ORDER BY personal_model_id ASC
                """,
                (alpha.personal_model_id, beta.personal_model_id),
            ).fetchall()

        self.assertEqual([tuple(row) for row in profile_rows], [("you",)])

    def test_create_elephant_reuses_personal_model_without_clearing_growth(self) -> None:
        runtime = self._runtime()
        original = runtime.create_elephant(elephant_id="atlas")
        runtime.repository.upsert_personal_model_growth(
            PersonalModelGrowthState(
                profile_id=original.personal_model_id,
                growth_score=480,
                total_dialogues=12,
                total_tokens=3400,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        runtime.repository.delete_episodes((original.episode_id,))

        self.assertIsNotNone(runtime.repository.load_personal_model(original.personal_model_id))
        stale_growth = runtime.repository.load_personal_model_growth(original.personal_model_id)
        self.assertIsNotNone(stale_growth)
        assert stale_growth is not None
        self.assertEqual(stale_growth.growth_score, 480)

        recreated = runtime.create_elephant(elephant_id="atlas")

        self.assertEqual(recreated.personal_model_id, original.personal_model_id)
        refreshed_growth = runtime.repository.load_personal_model_growth(recreated.personal_model_id)
        self.assertIsNotNone(refreshed_growth)
        assert refreshed_growth is not None
        self.assertEqual(refreshed_growth.growth_score, 480)
        elephant_state = runtime.state_for_elephant("atlas")
        self.assertIsNotNone(elephant_state)
        assert elephant_state is not None
        self.assertEqual(elephant_state.elephant_name, "Atlas")

    def test_elephants_get_isolated_elephant_identity_under_one_personal_model(self) -> None:
        runtime = self._runtime()
        alpha = runtime.create_elephant(elephant_id="alpha")
        beta = runtime.create_elephant(elephant_id="beta")

        alpha_state = runtime.state_for_elephant("alpha")
        beta_state = runtime.state_for_elephant("beta")
        root_profile = runtime.current_profile()

        self.assertEqual(alpha.personal_model_id, beta.personal_model_id)
        self.assertIsNotNone(alpha_state)
        self.assertIsNotNone(beta_state)
        assert alpha_state is not None
        assert beta_state is not None
        self.assertEqual(alpha_state.elephant_name, "Alpha")
        self.assertEqual(beta_state.elephant_name, "Beta")
        self.assertEqual(alpha_state.personal_model_id, "you")
        self.assertEqual(beta_state.personal_model_id, "you")
        self.assertEqual(root_profile.state.display_name, "Elephant Agent")
        self.assertIsNone(root_profile.elephant_identity_text)

    def test_start_session_keeps_the_requested_profile_binding(self) -> None:
        runtime = self._runtime(
            profile_payload={
                "profile_id": "profile-companion",
                "display_name": "elephant",
                "mode": "companion",
            }
        )
        session = runtime.start()

        inspected = runtime.inspect_session(session.episode_id)
        continuity = runtime.inspect_continuity(session_id=session.episode_id)

        self.assertEqual(inspected.personal_model_id, "you")
        self.assertEqual(continuity.profile.state.display_name, "you")
        self.assertFalse((runtime.paths.home_dir / "profiles" / "elephant%3Anova" / "profile.json").exists())

    def test_explain_next_step_does_not_mutate_profile_without_management_tools(self) -> None:
        runtime = self._runtime(
            profile_payload={
                "profile_id": "profile-companion",
                "display_name": "Elephant Agent",
                "mode": "companion",
                "companion": {"initiative": "gentle"},
            }
        )
        session = runtime.start()

        outcome = runtime.explain_next_step(
            session_id=session.episode_id,
            prompt="Call me Bit. I'm building durable agent systems. Please keep replies concise and grounded for future turns.",
        )
        user = runtime.inspect_user(session_id=session.episode_id)
        relationship = runtime.inspect_relationship(session_id=session.episode_id)

        self.assertIsNone(user.preferred_name)
        self.assertEqual(user.communication_preferences, ())
        self.assertEqual(user.biography_fragments, ())
        self.assertEqual(relationship.continuity_notes, ())
        self.assertEqual(outcome.state.current_context_note, "")



if __name__ == "__main__":
    unittest.main()
