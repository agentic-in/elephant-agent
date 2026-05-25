"""Onboarding letter feature — write Elephant's first letter from PM grounding."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="onboarding_letter",
    tools=(
        "tool.diary.write",
    ),
    sop_fragment="""\
Write Elephant's first letter from the Personal Model facts in the evidence packet.
Only call tool.diary.write after the letter is ready.""",
    constraints="""\
- The diary metadata MUST include kind=onboarding_letter so the app can surface it as a letter.""",
    incompatible=("compress",),
)
