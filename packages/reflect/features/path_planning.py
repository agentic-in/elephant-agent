"""Onboarding Path planning feature — turn PM grounding into durable Paths."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="path_planning",
    tools=(
        "tool.personal_model.search",
        "tool.skill.list",
        "tool.paths.manage",
    ),
    sop_fragment="""\
Design or refresh durable Paths from the current Personal Model and conversation evidence.
Use tool.paths.manage to create 1-4 Paths that feel like living directions rather than work projects, and update existing Paths when the useful direction is already present.
Each Path should include small Flow steps that can move through later, next, working/reviewing, done, or stuck. Use the stored status keys `moving` for Working and `checking` for Reviewing when calling tools.
Mother may create a specialist baby elephant with create_baby when a role is clearly useful, define its role_title/role_prompt, then bind Flow steps with assignee_elephant_id. Do not create decorative or duplicate babies.
Assign a step to a baby elephant only when the evidence clearly implies a useful specialist; otherwise leave it unassigned for Mother to hold.
When a baby finishes work, write_summary should be a compact study note: the essential result, why it matters, the transferable method, and the shortest human_takeaway the user should absorb.
Use review_mode=trusted by default; the user can edit or delete Paths and Flow steps after Mother creates them.""",
    constraints="""\
- Do not create medical, legal, financial, or mental-health prescriptions.
- Do not overplan: keep the first Paths small enough for a human to review in one pass.
- Path titles should be warm, concrete, and user-facing, not generic project-management labels.
- Path metadata should include source=onboarding_paths and parent_learning_job_id when available.""",
    incompatible=("compress", "onboarding_letter"),
)
