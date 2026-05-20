from __future__ import annotations

import unittest

from packages.contracts.runtime import ElephantIdentityRecord, PersonalModelRuntimeState
from packages.state.projection import build_loaded_profile_from_state
from packages.state import CompanionSettings


class PersonalStateProjectionTest(unittest.TestCase):
    def test_build_loaded_profile_from_state_keeps_elephant_identity_out_of_persona_policy(self) -> None:
        loaded = build_loaded_profile_from_state(
            PersonalModelRuntimeState(
                profile_id="profile-companion",
                display_name="Elephant Agent",
                mode="companion",
            ),
            companion=CompanionSettings(
                personality_preset="custom",
                personality=("steady", "direct"),
                initiative="gentle",
            ),
            identity_record=ElephantIdentityRecord(
                elephant_id="profile-companion:elephant",
                profile_id="profile-companion",
                display_name="Elephant Agent",
                identity_mode="companion",
                personality_preset="custom",
                initiative="proactive",
                relational_stance="custom",
                working_style_contract="Operator-defined trait bundle.",
                governance_flags=("text-first",),
            ),
        )

        assert loaded.companion is not None
        self.assertEqual(loaded.companion.personality_preset, "custom")
        self.assertEqual(loaded.companion.personality, ("steady", "direct"))
        self.assertEqual(loaded.companion.initiative, "gentle")


if __name__ == "__main__":
    unittest.main()
