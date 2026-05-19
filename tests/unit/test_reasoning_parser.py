from __future__ import annotations

import unittest

from packages.models.reasoning_parser import (
    combine_reasoning_text,
    stitch_text_fragments,
)


class ReasoningParserTests(unittest.TestCase):
    def test_stitch_text_fragments_collapses_whitespace_only_tokens_between_english_words(
        self,
    ) -> None:
        stitched = stitch_text_fragments("Inspect", "\n", "the", "\n\n", "latest", " ", "release")

        self.assertEqual(stitched, "Inspect the latest release")

    def test_stitch_text_fragments_prioritizes_spaces_over_guessing_subword_joins(
        self,
    ) -> None:
        stitched = stitch_text_fragments("3.", "X", "un", "zhuo", " ", "lives", " ", "in", " ", "Cheng", "du")

        self.assertEqual(stitched, "3. X un zhuo lives in Cheng du")

    def test_stitch_text_fragments_restores_word_boundaries_by_default(self) -> None:
        stitched = stitch_text_fragments("The", "user", "asked", "about", "X", "un", "zhuo", "in", "Cheng", "du", ".")

        self.assertEqual(stitched, "The user asked about X un zhuo in Cheng du.")

    def test_stitch_text_fragments_does_not_guess_camel_case_boundaries(self) -> None:
        stitched = stitch_text_fragments("LoopStatePr", "ojection", "contains", "Retrieved", "Memory", "entries", ".")

        self.assertEqual(stitched, "LoopStatePr ojection contains Retrieved Memory entries.")

    def test_stitch_text_fragments_keeps_mixed_language_reasoning_readable(
        self,
    ) -> None:
        stitched = stitch_text_fragments("先看", "\n", "release", "\n", "notes", "。", "\n", "Then", "\n", "verify")

        self.assertEqual(stitched, "先看release notes。 Then verify")

    def test_combine_reasoning_text_deduplicates_equivalent_multiline_reasoning(
        self,
    ) -> None:
        combined = combine_reasoning_text(
            "先看release notes。 Then verify",
            "先看\nrelease\nnotes。\nThen\nverify",
        )

        self.assertEqual(combined, "先看release notes。 Then verify")


if __name__ == "__main__":
    unittest.main()
