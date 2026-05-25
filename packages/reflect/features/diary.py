"""Diary writing feature — write reflective daily entries."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="diary",
    tools=(
        "tool.diary.write",
        "tool.diary.list",
        "tool.conversation.search",
        "tool.personal_model.search",
    ),
    sop_fragment="""\
You MUST call tools in this order:
1. Call tool.diary.list with limit=5 to check if an entry already exists for the target date.
2. Call tool.conversation.search with mode=discover, expr=<target_date>, timezone=<user_timezone> to find conversations for that day.
3. If conversations found, call tool.conversation.search with mode=recall for the most active time range.
4. Call tool.personal_model.search with query about the user's current state/mood/focus.
5. Call tool.diary.write with entry_date=<target_date> and the reflective diary content.

The diary entry should be reflective, emotionally honest, in second person (addressing the user as "你"/"you"), 400-800 words in the user's first language.
Do NOT skip any tool calls. Every diary entry MUST end with a tool.diary.write call.""",
    constraints="""\
- This is creative writing, NOT a summary or transcript.
- Write as a companion who deeply knows this person, not a neutral observer.
- Use the PM portrait to ground your interpretation.
- If no conversations happened, write a shorter entry (2-3 paragraphs) reflecting on the quiet.
- Content MUST start with a markdown heading (# Title) — evocative, not a date.
- You MUST call tool.diary.write — producing text output alone is NOT sufficient.""",
    incompatible=("compress",),
)
