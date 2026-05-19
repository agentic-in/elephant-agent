"""Skill optimization feature — derive improvement candidates from historical tool trajectories."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="skill_optimization",
    tools=(
        "tool.skill.list",
        "tool.skill.view",
        "tool.skill.manage",
        "tool.personal_model.search",
        "tool.personal_model.update",
    ),
    sop_fragment="""\
- tool.personal_model.search mode=inventory lens=world status=all → inspect existing world.skills.optimization.* and world.skills.affinity.* topics before writing.
- tool.skill.list → inspect the current skill catalog.
- tool.skill.view → inspect the target skill before proposing or applying a candidate.
- Review the supplied trajectory signals and optimization candidates in the evidence packet.
- For each new candidate, resolve an exact topic under world.skills.optimization.<target_scope>.<candidate_key> or world.skills.optimization.new.<candidate_key>.
- Use tool.personal_model.search with the exact topic to capture the candidate ref before correcting or applying an existing candidate.
- Write new candidates with tool.personal_model.update action=remember, lens=world, source=learned, recall_policy=review, metadata.review_status=pending, and metadata.retention_lifecycle=draft.
- Only apply an approved candidate when the target skill is authored; use tool.skill.manage action=update first, then update the candidate review_status to applied.
- Preserve rejected candidates for audit and duplicate suppression; do not delete them just to hide them.""",
    constraints="""\
- Only create optimization candidates from supplied signals with confidence >= 0.6.
- Never include user conversation text, assistant prose, or tool arguments in candidate summaries.
- topic MUST follow one of these formats:
  - world.skills.optimization.<skill_index_id>.<candidate_key>
  - world.skills.optimization.new.<candidate_key>
- lens MUST be world.
- All candidate writes MUST set recall_policy=review.
- metadata MUST include candidate_key, projection_policy=skill_optimization_candidate, review_status=pending for new candidates, and retention_lifecycle=draft.
- Do not call tool.skill.manage action=update unless the candidate is approved and the target skill is authored.
- Before action=correct, action=restore, or action=delete on an existing candidate fact, resolve the exact ref first with tool.personal_model.search.""",
    requires=("skills",),
)
