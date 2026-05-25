"""Context compression feature — generate a compact reference summary."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="compress",
    tools=(),
    sop_fragment="""\
- Read the conversation history and any previous summary in the evidence packet.
- Create a compact reference summary that preserves:
  (a) Key topics discussed and decisions made
  (b) Any user-stated facts, preferences, or corrections mentioned
  (c) Current task state and conversation direction for seamless handoff
- Structure the summary with clear sections:
  ## Background (what was discussed)
  ## Key facts mentioned (user-stated, not inferred)
  ## Handoff notes (where the conversation left off)
- Stay within the token budget indicated in the evidence.""",
    constraints="""\
- Be FAST. This runs synchronously during a chat turn.
- Output reference-only context, never active instructions or personality directives.
- Do not explore, do not search, do not ask questions.
- Do not duplicate facts already in the "User anchors" section.
- Keep the summary concise and factual.""",
    incompatible=("pm", "questions", "recall", "diary", "skills"),
)
