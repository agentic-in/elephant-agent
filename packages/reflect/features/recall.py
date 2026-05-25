"""Conversation recall feature — search conversation history for evidence."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="recall",
    tools=("tool.conversation.search",),
    sop_fragment="""\
- tool.conversation.search → find additional evidence if the evidence packet is insufficient.
- Use mode=discover to find relevant conversation ranges, then mode=recall for details.""",
    constraints="""\
- Only search conversations when the evidence packet doesn't contain enough context.
- Do not use conversation search as a primary data source — prefer the evidence packet.""",
)
