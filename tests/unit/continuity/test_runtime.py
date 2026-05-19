from __future__ import annotations

from datetime import datetime, timezone
import unittest

from packages.continuity import (
    apply_episode_continuity_state,
    build_relationship_policy,
    build_episode_continuity_state,
)
from packages.contracts.layers import Episode


def _episode(
    episode_id: str,
    *,
    parent_episode_id: str | None = None,
    interruption_state: str | None = None,
) -> Episode:
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Episode(
        episode_id=episode_id,
        state_id="state:test",
        personal_model_id="personal-model-companion",
        entry_surface="test",
        elephant_id="",
        status="open",
        started_at=timestamp,
        updated_at=timestamp,
        parent_episode_id=parent_episode_id,
        interruption_state=interruption_state,
    )


class ContinuityRuntimeTests(unittest.TestCase):
    def test_build_episode_continuity_state_inherits_ancestor_interruption(
        self,
    ) -> None:
        parent = _episode("root", interruption_state="Need to finish the plan")
        child = _episode("child", parent_episode_id="root")

        continuity = build_episode_continuity_state(
            child,
            lineage=(parent, child),
        )

        self.assertEqual(continuity.mode, "background")
        self.assertEqual(continuity.origin_episode_id, "root")
        self.assertEqual(continuity.lineage_episode_ids, ("root", "child"))
        self.assertEqual(continuity.inherited_interruption_state, "Need to finish the plan")
        self.assertNotIn("current-work item", continuity.summary)

    def test_build_episode_continuity_state_normalizes_generated_resume_text(
        self,
    ) -> None:
        episode = _episode(
            "child",
            parent_episode_id="root",
            interruption_state=(
                "resume durable work from episode root after interruption: Recover the thread; "
                "active elephant focus release checklist; immediate parent=root"
            ),
        )

        continuity = build_episode_continuity_state(episode, lineage=(episode,))

        self.assertEqual(continuity.mode, "background")
        self.assertEqual(continuity.inherited_interruption_state, "Recover the thread")

    def test_apply_episode_continuity_state_restores_inherited_interruption_when_needed(
        self,
    ) -> None:
        parent = _episode("root", interruption_state="Return to the design review")
        child = _episode("child", parent_episode_id="root")
        continuity = build_episode_continuity_state(child, lineage=(parent, child))

        restored = apply_episode_continuity_state(child, continuity)

        self.assertEqual(restored.interruption_state, "Return to the design review")

    def test_build_relationship_projection_policy_summary_is_text_first(self) -> None:
        policy = build_relationship_policy("companion", text_first=True)

        self.assertTrue(policy.allows("relationship"))
        self.assertFalse(policy.allows("voice"))
        self.assertIn("companion text-first continuity", policy.summary())
