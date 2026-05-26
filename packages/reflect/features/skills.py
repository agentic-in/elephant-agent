"""Skill affinity feature — inspect skill catalog and write affinity facts."""

from __future__ import annotations

from .types import Feature

FEATURE = Feature(
    feature_id="skill_affinity",
    tools=(
        "tool.skill.list",
        "tool.skill.view",
        "tool.personal_model.search",
        "tool.personal_model.update",
    ),
    sop_fragment="""\
- tool.skill.list → check available skills in the catalog.
- tool.personal_model.search mode=inventory → inspect existing world.skills.affinity.* claims before writing.
- For each skill with clear evidence of user relevance, write one affinity claim:
  lens=world, topic=world.skills.affinity.{skill_index_id}
  Include metadata: skill_id=<skill_id>, index_id=<skill_index_id>, projection_policy=skill_shelf_candidate
  Text should explain WHY this skill matches the user (one sentence, grounded in evidence).
- When trigger=init or trigger=init_profile, treat explicit init answers and bootstrapped
  Personal Model facts as valid evidence for early skill affinity.
- Match user interests, tools, projects, and working style to available skills.""",
    constraints="""\
- Only write affinity claims when there is clear evidence of relevance from the supplied evidence.
- Do not guess skill preferences from sparse or ambiguous data.
- For trigger=init or trigger=init_profile, sparse conversation history is expected; do not
  require conversation turns if init answers or bootstrapped PM facts clearly
  match a skill.
- topic MUST follow the format: world.skills.affinity.{skill_index_id}
  where skill_index_id uses underscores (e.g. world.skills.affinity.web_search).
- lens MUST be world.
- metadata MUST include skill_id, index_id, and projection_policy=skill_shelf_candidate.""",
)
