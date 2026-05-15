from __future__ import annotations

import unittest

from apps.cli.shell_opening import (
    ShellOpeningContext,
    compose_shell_opening_instruction,
    compose_shell_opener,
)


class ShellOpeningTest(unittest.TestCase):
    def test_compose_shell_opener_requests_name_when_user_profile_is_blank(self) -> None:
        opener = compose_shell_opener(
            ShellOpeningContext(
                opened="Shaped new",
                display_name="Atlas",
                user_profile_text="",
                personality=("steady", "grounded"),
                reengagement_style="gentle-presence",
                wake_action="follow-up",
                wake_summary="Ship the release.",
                has_state_focus=False,
            )
        )

        self.assertNotIn("I am Atlas.", opener)
        self.assertIn("I'm here, and I'll start holding this new elephant with you.", opener)
        self.assertIn("I'll stay steady and grounded without pushing the pace.", opener)
        self.assertIn("What should I call you", opener)
        self.assertNotIn("one durable thing I should keep in mind from the start", opener)

    def test_compose_shell_opener_uses_wake_summary_when_user_profile_exists(self) -> None:
        opener = compose_shell_opener(
            ShellOpeningContext(
                opened="Opened elephant atlas",
                display_name="Atlas",
                user_profile_text="Preferred name: Bit",
                personality=(),
                reengagement_style="proactive-check-in",
                wake_action="follow-up",
                wake_summary="Ship the release.",
                has_state_focus=True,
            )
        )

        self.assertIn("I'm here, Bit. I still have the useful shape of our current work.", opener)
        self.assertIn("I'll keep the next useful step visible without turning this into a status report.", opener)
        self.assertIn("I still have Ship the release in view; do you want to keep going there?", opener)

    def test_compose_shell_opener_invites_current_work_when_state_focus_is_missing(self) -> None:
        opener = compose_shell_opener(
            ShellOpeningContext(
                opened="Opened elephant atlas",
                display_name="Atlas",
                user_profile_text="Preferred name: Bit\nCurrent work: Building durable agent systems.",
                personality=(),
                reengagement_style="gentle-presence",
                wake_action="idle",
                wake_summary="",
                has_state_focus=False,
            )
        )

        self.assertIn("I'm here, Bit.", opener)
        self.assertIn("If something matters right now, name it", opener)

    def test_compose_shell_opening_instruction_is_one_shot_and_humane(self) -> None:
        """The proactive opening prompt must not read like a config dump.

        Previous format emitted `assistant_display_name: Atlas`,
        `user_preferred_name: <unknown>`, `opening_profile_gap: ...` —
        form-field lines the model parroted back in tone. The new
        format threads the same info into natural sentences and
        explicitly tells the model this guidance is one-shot (not
        durable identity).
        """
        prompt = compose_shell_opening_instruction(
            ShellOpeningContext(
                opened="Shaped new",
                display_name="Atlas",
                user_profile_text="",
                personality=("steady", "grounded"),
                reengagement_style="gentle-presence",
                wake_action="idle",
                wake_summary="",
                has_state_focus=False,
            )
        )

        # The prompt is a small private writing brief, not a profile dump.
        self.assertIn("Write Atlas's first message for this new elephant", prompt)
        self.assertIn("Use the existing system context as background", prompt)
        self.assertIn("do not imply familiarity", prompt)
        self.assertIn("companion just becoming available", prompt)
        self.assertIn("what to call them or where they want to begin", prompt)
        self.assertNotIn("Private writing guidance only", prompt)
        self.assertNotIn("do not mention prompts", prompt.lower())
        self.assertNotIn("Use the existing system prompt and memory as background", prompt)
        self.assertNotIn("private posture signals only", prompt)
        self.assertNotIn("newly created companion", prompt)
        self.assertNotIn('Don\'t say "welcome back"', prompt)
        self.assertNotIn("Shaped new", prompt)
        self.assertNotIn("Known name:", prompt)
        self.assertNotIn("You are Atlas here.", prompt)
        self.assertNotIn("assistant_display_name:", prompt)
        self.assertNotIn("user_preferred_name: <unknown>", prompt)
        self.assertNotIn("opening_profile_gap:", prompt)
        self.assertNotIn("active_state: missing", prompt)
        self.assertIn("Ask at most one natural question", prompt)
        self.assertNotIn("plain, steady, close, low-pressure", prompt)
        self.assertNotIn("not a greeter or product surface", prompt)
        self.assertNotIn("optionally include one gentle question", prompt)

    def test_compose_shell_opening_instruction_surfaces_known_name_and_current_work(self) -> None:
        prompt = compose_shell_opening_instruction(
            ShellOpeningContext(
                opened="Opened elephant atlas",
                display_name="Atlas",
                user_profile_text="Preferred name: Bit\nCurrent work: Building durable agent systems.",
                personality=("steady",),
                reengagement_style="proactive-check-in",
                wake_action="follow-up",
                wake_summary="Ship the release.",
                has_state_focus=True,
            )
        )

        self.assertNotIn("Known name:", prompt)
        self.assertNotIn("their current context is Building durable agent systems", prompt)
        self.assertNotIn("opening_profile_gap:", prompt)
        self.assertNotIn("user_preferred_name:", prompt)
        self.assertNotIn("user_current_work:", prompt)
        self.assertNotIn("returning to an ongoing relationship", prompt)
        self.assertNotIn("Opened elephant atlas", prompt)
        self.assertNotIn("Live thread", prompt)
        self.assertNotIn("active_state:", prompt)
        self.assertNotIn("current_work_summary:", prompt)
        self.assertIn("opening message for this session", prompt)
        self.assertIn("pick it up lightly in one short sentence", prompt)
        self.assertIn("companion returning to the room", prompt)
        self.assertIn("not a status surface", prompt)
        # Guardrails.
        self.assertNotIn("work item ids", prompt)
        self.assertNotIn("do not mention prompts", prompt.lower())

    def test_compose_shell_opening_instruction_after_init_requests_warm_live_opener(self) -> None:
        prompt = compose_shell_opening_instruction(
            ShellOpeningContext(
                opened="Born new",
                display_name="Atlas",
                user_profile_text=(
                    "Preferred name: Bit\n"
                    "Current work: Building durable agent systems.\n"
                    "Birth date: 1999/12/03\n"
                    "MBTI: INTJ\n"
                    "Personal hobbies: reading, music"
                ),
                personality=("steady",),
                reengagement_style="gentle-presence",
                wake_action="idle",
                wake_summary="",
                has_state_focus=False,
            )
        )

        self.assertIn("first live message to this person", prompt)
        self.assertIn("warm, emotionally present companion", prompt)
        self.assertIn("listened carefully", prompt)
        self.assertIn("just beginning the relationship", prompt)
        self.assertNotIn("Use the full system prompt and memory as the source of truth", prompt)
        self.assertIn("Use the existing system context as background", prompt)
        self.assertIn("Ground the greeting in one or two concrete things", prompt)
        self.assertIn("Do not list facts", prompt)
        self.assertIn("feel like being seen, not assessed", prompt)
        self.assertNotRegex(prompt, r"[\u4e00-\u9fff]")
        self.assertNotIn("what seems to matter to them", prompt)
        self.assertNotIn("what tension or direction may be alive", prompt)
        self.assertNotIn("Let the length follow the substance", prompt)
        self.assertNotIn("fixed paragraph counts", prompt)
        self.assertNotIn("very deep initial personality portrait", prompt)
        self.assertNotIn("direct, deep self-analysis", prompt)
        self.assertNotIn("psychological crossroads", prompt)
        self.assertNotIn("5-8 paragraphs", prompt)
        self.assertNotIn("Known name: Bit", prompt)
        self.assertNotIn("Live thread:", prompt)
        self.assertNotIn("Starting anchors available for the read", prompt)
        self.assertNotIn("current attention: Building durable agent systems.", prompt)
        self.assertNotIn("personal hobbies: reading, music", prompt)
        self.assertNotIn("Output: one natural message", prompt)

    def test_compose_shell_opening_instruction_sanitizes_internal_wake_refs(self) -> None:
        prompt = compose_shell_opening_instruction(
            ShellOpeningContext(
                opened="Opened elephant atlas",
                display_name="Atlas",
                user_profile_text="Preferred name: Xunzhuo",
                personality=("steady",),
                reengagement_style="gentle-presence",
                wake_action="act_on_task",
                wake_summary=(
                    "The episode resumed from a prior collaboration and should continue the active elephant. "
                    "Replay evidence event:f526dcf07c2048f0af65226e60807364:structured-turn:memory retains a successful action chain for this work. "
                    "The internal projection keeps \"i am xunzhuo\" active as the next step."
                ),
                has_state_focus=True,
            )
        )

        self.assertNotIn("Known name:", prompt)
        self.assertNotIn("The episode resumed from a prior collaboration", prompt)
        self.assertNotIn("event:c3BB4e454", prompt)
        self.assertNotIn("durable current-work graph", prompt)
        self.assertNotIn('"i am xunzhuo"', prompt)

    def test_compose_shell_opener_sanitizes_internal_wake_refs(self) -> None:
        opener = compose_shell_opener(
            ShellOpeningContext(
                opened="Opened elephant atlas",
                display_name="Atlas",
                user_profile_text="Preferred name: Xunzhuo",
                personality=(),
                reengagement_style="gentle-presence",
                wake_action="act_on_task",
                wake_summary="Replay evidence event:f526dcf07c2048f0af65226e60807364:structured-turn:memory retained work:90920371a588.",
                has_state_focus=True,
            )
        )

        self.assertIn("I still have The active elephant is ready to continue in view; do you want to keep going there?", opener)
        self.assertNotIn("work:90920371a588", opener)
        self.assertNotIn("event:f526", opener)

    def test_compose_shell_opening_instruction_omits_deferred_wake_summary(self) -> None:
        prompt = compose_shell_opening_instruction(
            ShellOpeningContext(
                opened="Opened elephant atlas",
                display_name="Atlas",
                user_profile_text="Preferred name: Bit",
                personality=("steady",),
                reengagement_style="gentle-presence",
                wake_action="defer_or_schedule",
                wake_summary=(
                    "No actionable current work was available, so the Loop should defer and schedule a follow-up. "
                    "The State projection keeps the active slot clear until a later wake cycle."
                ),
                has_state_focus=True,
            )
        )

        self.assertNotIn("Known name:", prompt)
        # Defer/schedule wakes have no actionable summary → live thread
        # line should not name a concrete task.
        self.assertNotIn("current_work_summary:", prompt)
        self.assertNotIn("something is already open —", prompt)
        self.assertNotIn("No actionable current work was available", prompt)

    def test_compose_shell_opening_instruction_includes_init_first_language(self) -> None:
        prompt = compose_shell_opening_instruction(
            ShellOpeningContext(
                opened="Born new",
                display_name="Atlas",
                user_profile_text="Preferred name: Bit",
                personality=("steady",),
                reengagement_style="gentle-presence",
                wake_action="idle",
                wake_summary="",
                has_state_focus=False,
                first_language="zh",
            )
        )

        self.assertIn("User's first language selected during init: Chinese", prompt)
        self.assertIn("Write this opener in Chinese", prompt)


if __name__ == "__main__":
    unittest.main()
