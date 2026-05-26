"""Skill evolution feature — create pending skill drafts from repeated workflows."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="skill_evolution",
    tools=(
        "tool.skill.list",
        "tool.skill.view",
        "tool.skill.draft",
        "tool.conversation.search",
        "tool.personal_model.search",
    ),
    sop_fragment="""\
- Review the supplied Skill Evolution Evidence packet first. It is the source of truth.
- tool.skill.list → inspect the current skill catalog and pending skill drafts.
- tool.personal_model.search mode=inventory lens=world status=all → inspect existing world.skills.affinity.* topics before deciding overlap.
- tool.skill.view → inspect an overlapping target skill before proposing an update draft.
- Use tool.conversation.search only as a targeted recall step for the episode IDs or date ranges named in the evidence packet.
- For each strong candidate, choose exactly one action:
  reuse_existing, update_existing_skill_draft, create_new_skill_draft, or skip.
- Call tool.skill.draft only for create_new_skill_draft or update_existing_skill_draft. Drafts are disabled by default and require user approval in the Skills surface before normal agent loops can use them.
- Prefer one high-value draft over several weak drafts.""",
    constraints="""\
- Only call tool.skill.draft for candidates listed in Skill Evolution Candidate Records with confidence >= 0.6.
- Do not write Personal Model skill optimization facts. The skill draft is the review artifact.
- Do not enable, install, delete, or directly update active skills.
- Do not include raw private conversation text, assistant prose, or tool arguments in the draft.
- Skill drafts must follow skill-creator principles: concise trigger-oriented description, stable inputs, repeatable workflow, clear outputs, and validation guidance.
- If an existing skill already covers the workflow, skip or create an update draft only when the evidence shows a concrete missing step, trigger, tool path, or validation rule.""",
    requires=("skill_affinity",),
)
