from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import packages.state as state_exports
from packages.contracts.runtime import PersonalModelRuntimeState
from packages.state import (
    CompanionSettings,
    build_loaded_profile_from_state,
    build_prompt_contract,
    profile_with_authored_elephant_identity,
    render_user_profile_text,
    write_elephant_identity_file,
)


class PromptContractTest(unittest.TestCase):
    """Prompt contract rendering from a constructed LoadedProfile.

    The runtime loads LoadedProfile straight off the canonical State row +
    persisted canonical records; the prompt contract never reads a
    ``profile.json`` manifest. These tests build a LoadedProfile directly
    with ``state.display_name`` set to the companion name — mirroring what
    :func:`packages.state.load_runtime_profile` returns at runtime.
    """

    def _build_loaded_profile(self, *, display_name: str = "Aeon", elephant_identity_text: str | None = None):
        runtime_state = PersonalModelRuntimeState(
            profile_id="you",
            display_name=display_name,
            mode="companion",
            preferences=("tone:steady", "verbosity:concise"),
        )
        companion = CompanionSettings(
            personality_preset="companion",
            initiative="proactive",
            notes=("recover long arcs",),
        )
        return build_loaded_profile_from_state(
            runtime_state,
            manifest={},
            companion=companion,
            profile_dir="",
            manifest_path=None,
            elephant_identity_text=elephant_identity_text or "Protect the active elephant and stay exact.",
            user_profile_text=render_user_profile_text(
                preferred_name="Bit",
                current_work="Building durable agent systems.",
                durable_notes=(
                    "Prefers direct updates over filler.",
                    "Wants long-horizon context carried across sessions.",
                ),
            ),
        )

    def test_full_prompt_contract_includes_canonical_identity_and_user_sections(self) -> None:
        loaded = self._build_loaded_profile()
        contract = build_prompt_contract(loaded, prompt_mode="full")

        self.assertEqual(
            contract.section_names,
            (
                "system-layer-contract",
                "elephant-identity",
                "understanding-tool-policy",
            ),
        )
        self.assertEqual(
            contract.stable_prefix_refs[:2],
            (
                "### Who you are",
                "- You are Aeon, the companion this person keeps coming back to.",
            ),
        )
        rendered = "\n".join(contract.instruction_refs)
        self.assertIn("You are Aeon, the companion this person keeps coming back to.", rendered)
        # Humanized prompt: the old framework-speak bullets must be gone.
        self.assertNotIn("active elephant identity for one durable elephant", rendered)
        self.assertNotIn("Canonical containment", rendered)
        self.assertNotIn("Personal Model -> Elephant -> Episode -> Loop -> Step", rendered)
        self.assertIn("### Your own voice", rendered)
        self.assertIn("Protect the active elephant and stay exact.", rendered)
        self.assertNotIn("### Carrying context forward", rendered)
        self.assertNotIn("### Tracking work in a session", rendered)
        self.assertIn("`tool.todo.manage`", rendered)
        self.assertIn("### Understanding tools", rendered)
        self.assertIn("Use tools quietly", rendered)
        self.assertIn("`tool.personal_model.update`", rendered)
        self.assertIn("`tool.personal_model.search`", rendered)
        self.assertIn("explicitly asks you to remember", rendered)
        self.assertIn("do not say it was remembered unless the update tool succeeded", rendered)
        self.assertIn("`tool.conversation.search`", rendered)
        self.assertNotIn("`tool.conversation.recall`", rendered)
        self.assertNotIn("`tool.conversation.timeline`", rendered)
        self.assertNotIn("`tool.memory.note`", rendered)
        self.assertNotIn("`tool.memory.recall`", rendered)
        self.assertNotIn("preferred name", rendered.lower())
        self.assertIn("owned by one lens/topic", rendered)
        self.assertIn("grounded in the user's words", rendered)
        # Old state-write / identity sections should stay removed.
        self.assertNotIn("### State Write Policy", rendered)
        self.assertFalse(hasattr(state_exports, "build_runtime_contract_section"))
        self.assertFalse(hasattr(state_exports, "build_state_write_policy_section"))
        self.assertNotIn("Custom Elephant Agent charter for tests.", rendered)
        self.assertNotIn("ELEPHANT.md", rendered)
        self.assertNotIn("identity-display-name=", rendered)
        self.assertNotIn("section:identity-capsule", rendered)
        self.assertNotIn("elephant-charter=", rendered)
        # Old flat form-field listings must be gone.
        self.assertNotIn("section:user-snapshot", rendered)
        self.assertNotIn("user-known-fields=", rendered)
        self.assertNotIn("user-canonical-fields=", rendered)
        self.assertNotIn("user-open-facts-count=", rendered)
        # LoadedProfile user snapshots stay out of the stable prompt; active Personal Model facts are injected separately.
        self.assertNotIn("### What you know about the user", rendered)
        self.assertNotIn("- Preferred name: Bit", rendered)
        self.assertNotIn("Continuity reminders for this elephant: recover long arcs.", rendered)
        self.assertIn("Use `tool.personal_model.questions` only when one timely question would improve future help.", rendered)
        self.assertIn("Keep Personal Model writes small", rendered)
        self.assertNotIn("state-onboarding=", rendered)
        self.assertNotIn("grounding-policy=", rendered)

    def test_minimal_prompt_contract_stays_compact_but_keeps_canonical_user_snapshot(self) -> None:
        loaded = self._build_loaded_profile()
        contract = build_prompt_contract(loaded, prompt_mode="minimal")

        self.assertEqual(
            contract.section_names,
            (
                "system-layer-contract",
                "elephant-identity",
                "understanding-tool-policy",
            ),
        )
        rendered = "\n".join(contract.instruction_refs)
        self.assertIn("### Who you are", rendered)
        self.assertIn("You are Aeon", rendered)
        self.assertIn("### Your own voice", rendered)
        self.assertIn("Protect the active elephant and stay exact.", rendered)
        # Minimal mode drops posture + continuity-reminder bullets.
        self.assertNotIn("Posture to carry:", rendered)
        self.assertNotIn("Initiative: proactive", rendered)
        # Continuity reminders only show up in full mode.
        self.assertNotIn("Continuity reminders for this elephant:", rendered)
        self.assertNotIn("### What you know about the user", rendered)
        self.assertNotIn("- Preferred name: Bit", rendered)
        self.assertNotIn("- Prefers direct updates over filler.", rendered)
        self.assertNotIn("section:user-snapshot", rendered)
        self.assertNotIn("user-known-fields=", rendered)
        self.assertNotIn("### State Write Policy", rendered)
        self.assertNotIn("state-onboarding=", rendered)
        self.assertNotIn("grounding-policy=", rendered)

    def test_prompt_contract_prefers_canonical_state_display_name(self) -> None:
        loaded = self._build_loaded_profile(
            display_name="Leah",
            elephant_identity_text="You are Leah, a steady companion on one continuous line with this person.",
        )
        contract = build_prompt_contract(loaded, prompt_mode="full")

        rendered = "\n".join(contract.stable_prefix_refs)
        self.assertIn("You are Leah, the companion this person keeps coming back to.", rendered)
        self.assertNotIn("You are Aeon, the companion this person keeps coming back to.", rendered)

    def test_authored_elephant_file_overlays_state_identity_before_prompt(self) -> None:
        loaded = self._build_loaded_profile(
            display_name="You",
            elephant_identity_text="State cache says stay quiet and stale.",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            elephant_root = Path(tmpdir) / "leah"
            write_elephant_identity_file(
                elephant_root,
                "<!-- file metadata -->\n\nFile-authored Leah is playful, precise, and alive.",
            )
            authored = profile_with_authored_elephant_identity(loaded, elephant_root)

        contract = build_prompt_contract(authored, prompt_mode="full")

        rendered = "\n".join(contract.stable_prefix_refs)
        self.assertIn("You are Leah, the companion this person keeps coming back to.", rendered)
        self.assertIn("File-authored Leah is playful, precise, and alive.", rendered)
        self.assertNotIn("State cache says stay quiet and stale.", rendered)
        self.assertNotIn("file metadata", rendered)

    def test_generated_elephant_charter_is_not_duplicated_as_custom_note(self) -> None:
        generated_elephant_identity_text = "\n".join(
            (
                "You are Aeon, a steady companion on one continuous line with this person.",
                "Posture: Steady, present, and continuity-first without losing boundaries.",
                "Voice you keep: steady, present, grounded.",
                "Initiative: proactive.",
                "Carry continuity with care, protect the trust you've built, and let this person refine who you are over time.",
            )
        )
        loaded = self._build_loaded_profile(elephant_identity_text=generated_elephant_identity_text)
        contract = build_prompt_contract(loaded, prompt_mode="full")

        rendered = "\n".join(contract.stable_prefix_refs)
        self.assertIn("You are Aeon, the companion this person keeps coming back to.", rendered)
        self.assertNotIn("Elephant-specific note:", rendered)


if __name__ == "__main__":
    unittest.main()
