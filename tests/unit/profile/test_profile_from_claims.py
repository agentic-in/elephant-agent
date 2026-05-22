from __future__ import annotations

from datetime import datetime, timezone
import unittest

from packages.contracts import Fact
from packages.state.profile_from_claims import derive_profile_from_claims


class ProfileFromClaimsTest(unittest.TestCase):
    def test_explicit_profile_anchor_wins_over_learned_claim(self) -> None:
        now = datetime.now(timezone.utc)
        facts = (
            Fact(
                fact_id="fact:agent-name",
                personal_model_id="profile",
                lens="identity",
                text="训灼",
                confidence=0.72,
                committed_at=now,
                source="pm_agent_promote",
                metadata={
                    "topic": "identity.anchor.name.preferred",
                    "source_kind": "learned",
                },
            ),
            Fact(
                fact_id="fact:init-name",
                personal_model_id="profile",
                lens="identity",
                text="Bit",
                confidence=1.0,
                committed_at=now,
                source="user_explicit",
                metadata={
                    "topic": "identity.anchor.name.preferred",
                },
            ),
        )

        profile = derive_profile_from_claims(facts)

        self.assertEqual(profile["preferred_name"], "Bit")


if __name__ == "__main__":
    unittest.main()
