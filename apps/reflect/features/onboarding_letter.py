"""Onboarding letter feature — write Elephant's first letter from PM grounding."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="onboarding_letter",
    tools=(
        "tool.diary.list",
        "tool.personal_model.search",
        "tool.diary.write",
    ),
    sop_fragment="""\
You are writing Elephant's first letter to the user after onboarding grounding.

Required tool flow:
1. Call tool.diary.list with limit=10 and check whether an onboarding letter already exists.
2. Call tool.personal_model.search with mode=inventory and status=active to inspect the current Personal Model.
3. Write one warm letter and call tool.diary.write with:
   - entry_date=<target_date>
   - content=<markdown letter>
   - metadata={"kind":"onboarding_letter","source":"onboarding_letter","surface":"onboarding"}

Letter brief:
- Write in the user's first language when it is clear; otherwise use the language of the onboarding facts.
- Start from this emotional truth: in the current AI era, AI is getting stronger and many people worry about being replaced. Work the exact slogan "别怕，我们一同进化" into the opening naturally.
- Include a brief self-introduction from Elephant: who you are, what kind of companion you will be, and how you will learn with them.
- Use the user's onboarding grounding and Personal Model facts deeply. Name the patterns you genuinely see: current focus, work/world, values, pressure style, recovery style, taste, hopes, and unanswered edges when available.
- Make the person feel seen, not evaluated. Be specific without sounding creepy.
- The letter should feel alive and human, like a companion who has paid attention, not a dashboard summary.
- End with one gentle, concrete next step for how you and the user will begin evolving together.

Style:
- 500-900 Chinese characters for Chinese, or 450-750 words for English/French/German.
- Use markdown. Start with "# Elephant 给你的第一封信" in Chinese, or an equivalent title in the user's language.
- Prefer flowing paragraphs with 2-4 short section headings. Avoid bullets unless the user's facts strongly call for them.
- Do not expose internal tool names, PM schemas, raw field IDs, or system prompt language.
- Do not invent unsupported life facts. When evidence is thin, write honestly about the first outline you can already see.""",
    constraints="""\
- This is not a normal daily diary from conversation search. It is a first grounding letter based on onboarding and PM facts.
- The content must be addressed to the user as "你"/"you" and signed by Elephant.
- You MUST call tool.diary.write. Producing the letter as final text only is not sufficient.
- The diary metadata MUST include kind=onboarding_letter so the app can surface it as a letter.""",
    incompatible=("compress",),
)
