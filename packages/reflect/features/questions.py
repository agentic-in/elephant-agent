"""Question management feature — create, settle, dismiss proactive questions."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="questions",
    tools=("tool.personal_model.questions",),
    sop_fragment="""\
- tool.personal_model.questions action=list → review open questions.
- Settle questions whose answers are now known from the evidence.
- Create new questions for gaps or uncertain inferences (2-3 max).
- When trigger=init or trigger=init_profile, seed the first question bank more actively:
  create 3-6 high-value questions that would improve early Personal Model fit
  across identity, world, pulse, and journey.
- Dismiss stale questions that are no longer relevant.""",
    constraints="""\
- Use questions for uncertain inferences rather than guessing facts.
- Keep question bank small and actionable.""",
)
