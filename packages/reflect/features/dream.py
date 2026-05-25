"""Dream feature — nightly Personal Model consolidation and cleanup."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="dream",
    tools=(
        "tool.personal_model.search",
        "tool.personal_model.update",
        "tool.conversation.search",
    ),
    sop_fragment="""\
Dream is a nightly consolidation pass, not episode-close learning.
It should freely explore the target day's conversations and the full PM inventory, then improve existing facts.

Required flow:
1. Call tool.conversation.search with mode=discover, expr=<target_date>, timezone=<user_timezone> to find the target day's conversations.
2. If useful ranges exist, call tool.conversation.search with mode=recall on the most relevant ranges.
3. Call tool.personal_model.search mode=inventory status=all to inspect the full topic layout.
4. For noisy or important topics, search the topic with status=all before editing.
5. Use tool.personal_model.update to correct, forget, dispute, restore, or remember claims only when the action improves PM quality.

Consolidate by pruning unreasonable facts, reorganizing topics, cleaning stale or synthetic claims,
deduplicating, merging overlapping claims, optimizing text, supplementing missing durable detail,
and compressing verbose facts into concise claims.""",
    constraints="""\
- Prefer cleanup and consolidation over creating new facts.
- Do not delete protected core identity claims. Correct them or leave them alone.
- Use forget for redundant or obsolete active claims; use dispute for unresolved contradictions.
- Use correct to replace verbose, vague, duplicated, or poorly scoped claims with concise versions.
- Preserve provenance through tool.personal_model.update rather than rewriting outside the tool.
- Every retained or new PM claim text must be short, clear, explicit, unambiguous, and information-dense.
- If there is not enough evidence to change a claim, do nothing and explain the no-op.""",
    incompatible=("compress",),
)
