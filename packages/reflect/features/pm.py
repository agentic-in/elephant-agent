"""PM fact writing feature — search, create, correct, retire personal model facts."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="pm",
    tools=(
        "tool.personal_model.search",
        "tool.personal_model.update",
    ),
    sop_fragment="""\
- tool.personal_model.search mode=inventory → see what already exists.
- Identify durable user facts from the evidence that are not yet in PM.
- Search relevant topics before writing to avoid duplicates.
- tool.personal_model.update → write each new/corrected claim (one call per change).
- Choose the lens that answers the right question about the person:
  identity (who they are), world (what is around them),
  pulse (how they are right now), journey (what they have been through).""",
    constraints="""\
- Do NOT store transient conversation details or system artifacts.
- Fewer high-quality claims over many weak ones.
- Claim text MUST be short, clear, explicit, unambiguous, and information-dense.
- Volatility annotation REQUIRED for every new/corrected claim:
  permanent (identity, stable preferences), situational (current state),
  ephemeral (short-lived, this week's mood).
- Second segment of topic MUST be a fixed facet for the chosen lens:
  identity → anchor | character | values | style | body
  world    → people | projects | tools | places | assets
  pulse    → chapter | focus | mood | blockers | intent
  journey  → lessons | patterns | decisions | milestones""",
)
