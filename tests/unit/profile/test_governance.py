from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from packages.contracts.runtime import PersonalModelRuntimeState
from packages.state import (
    CompanionSettings,
    build_companion_identity_state,
    build_companion_onboarding_state,
    parse_user_profile_content,
    user_profile_updates,
    merge_user_profile_text,
    missing_optional_user_fields,
    missing_required_user_fields,
    parse_user_profile_text,
    render_user_profile_text,
)
from packages.state.projection import build_loaded_profile_from_state


class UserProfileGovernanceTest(unittest.TestCase):
    def _load_profile(
        self,
        root: Path,
        *,
        display_name: str = "Aeon",
        user_profile_text: str | None = None,
    ):
        """Build a LoadedProfile with explicit identity (no profile.json).

        ``root`` is accepted for signature parity with the old fixture; it's
        unused now that identity data is never read from disk.
        """
        del root
        runtime_state = PersonalModelRuntimeState(
            profile_id="you",
            display_name=display_name,
            mode="companion",
        )
        companion = CompanionSettings(
            personality_preset="companion",
            initiative="proactive",
        )
        return build_loaded_profile_from_state(
            runtime_state,
            manifest={},
            companion=companion,
            profile_dir="",
            manifest_path=None,
            elephant_identity_text="Protect the active elephant and stay exact.",
            user_profile_text=user_profile_text,
        )

    def test_render_user_profile_text_round_trips_with_parser(self) -> None:
        rendered = render_user_profile_text(
            preferred_name="Bit",
            current_work="Building Elephant Agent.",
            current_city="Shanghai",
            dream="Build a durable AI companion.",
            durable_notes=("Prefers direct updates over filler.",),
        )

        parsed = parse_user_profile_text(rendered)
        parsed_content = parse_user_profile_content(rendered)

        self.assertEqual(parsed["preferred_name"], "Bit")
        self.assertEqual(parsed["current_work"], "Building Elephant Agent.")
        self.assertEqual(parsed["current_city"], "Shanghai")
        self.assertEqual(parsed["dream"], "Build a durable AI companion.")
        self.assertEqual(parsed_content.durable_notes, ("Prefers direct updates over filler.",))

    def test_missing_user_profile_fields_split_required_and_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = self._load_profile(Path(tmpdir))
            required = missing_required_user_fields(loaded)
            optional = missing_optional_user_fields(loaded)

        self.assertEqual(
            tuple(question.field_id for question in required),
            ("preferred_name", "current_work"),
        )
        self.assertEqual(
            tuple(question.field_id for question in optional[:2]),
            ("school", "current_city"),
        )

    def test_user_profile_updates_normalize_loose_field_labels(self) -> None:
        updates = user_profile_updates(
            {
                "Preferred name": "Bit",
                "Current work": "Building Elephant Agent.",
                "Movement hobby": "Climbing",
                "action": "set",
                "target": "user",
            }
        )

        self.assertEqual(
            updates,
            {
                "preferred_name": "Bit",
                "current_work": "Building Elephant Agent.",
                "movement_hobby": "Climbing",
            },
        )

    def test_merge_user_profile_text_preserves_existing_fields(self) -> None:
        merged = merge_user_profile_text(
            render_user_profile_text(
                preferred_name="Bit",
                current_work="Building Elephant Agent.",
                durable_notes=("Prefers direct updates.",),
            ),
            field_values={
                "movement_hobby": "Climbing",
            },
        )

        self.assertEqual(
            merged,
            render_user_profile_text(
                preferred_name="Bit",
                current_work="Building Elephant Agent.",
                movement_hobby="Climbing",
                durable_notes=("Prefers direct updates.",),
            ),
        )

    def test_parse_user_profile_content_keeps_low_loss_durable_notes(self) -> None:
        parsed = parse_user_profile_content(
            "\n".join(
                (
                    "Preferred name: Bit",
                    "Current work: Building Elephant Agent.",
                    "- Prefers concise direct updates.",
                    "Remember: Wants long-horizon elephant continuity kept intact.",
                    "Profile",
                )
            )
        )

        self.assertEqual(parsed.field_values["preferred_name"], "Bit")
        self.assertEqual(parsed.field_values["current_work"], "Building Elephant Agent.")
        self.assertEqual(
            parsed.durable_notes,
            (
                "Prefers concise direct updates.",
                "Wants long-horizon elephant continuity kept intact.",
            ),
        )

    def test_build_companion_identity_state_prefers_elephant_state_display_name(
        self,
    ) -> None:
        """``State.elephant_name`` → ``profile.state.display_name`` is canonical.

        ELEPHANT.md is authoring-only; the parser is a write-path helper, not a
        prompt-render source. ``build_companion_identity_state`` must honour
        the State row's name even when ELEPHANT.md contains a different one.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = self._load_profile(
                Path(tmpdir),
                display_name="Leah",
                user_profile_text="Preferred name: Bit",
            )
            loaded = build_loaded_profile_from_state(
                loaded.state,
                manifest=loaded.manifest,
                companion=loaded.companion,
                profile_dir=loaded.profile_dir,
                manifest_path=loaded.manifest_path,
                # ELEPHANT.md on disk contains a mismatched name — ignored at
                # render time. State.elephant_name (display_name) wins.
                elephant_identity_text=(
                    "# Elephant Identity: Leah\n"
                    "Display name: Leah\n"
                    "Mode: companion\n\n"
                    "You are Leah, a steady companion on one continuous line with this person."
                ),
                user_profile_text=loaded.user_profile_text,
            )
            identity = build_companion_identity_state(loaded)

        self.assertEqual(identity.display_name, "Leah")

    def test_onboarding_state_is_ready_without_file_first_profile_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = self._load_profile(Path(tmpdir))
            onboarding = build_companion_onboarding_state(loaded)

        self.assertEqual(onboarding.status, "ready")
        self.assertTrue(onboarding.ready)
        self.assertEqual(onboarding.missing_fields, ())
        self.assertEqual(onboarding.next_step, "continue-normal-conversation")
        self.assertIn("normal turns", onboarding.summary)
        self.assertEqual(
            tuple(checkpoint.status for checkpoint in onboarding.checkpoints),
            ("ready", "ready", "ready"),
        )


if __name__ == "__main__":
    unittest.main()
