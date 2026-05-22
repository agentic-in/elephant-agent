"""Shared prompt fragments for reflect agents."""

from __future__ import annotations

TOPIC_FORMAT = """
Topic format: <lens>.<facet>.<entity>[.<qualifier>]
- First segment must be the lens: identity, world, pulse, or journey.
- Second segment must be a fixed facet within that lens (see below).
- Minimum 3 segments: lens.facet.entity

Lens semantics and fixed facets:

identity — Who is this person? Durable attributes that do not change quickly.
  anchor     : Core identity facts — name, gender, birth date, age.
  character  : Personality patterns — MBTI, Big Five, decision style, rhythm, stress response.
  values     : Principles, beliefs, what they refuse to compromise.
  style      : Expression and collaboration — language, communication tone, companion posture, hobbies.
  body       : Long-term physical profile — allergies, chronic conditions, safety boundaries.

world — What is around this person? Their environment and relationships.
  people     : Relationships — family, friends, collaborators, clients, key contacts.
  projects   : Things they are working on — life-scale to week-scale.
  tools      : Software, devices, platforms, workflows they rely on.
  places     : Locations — home city, timezone, frequent places.
  assets     : Things they own or maintain — pets, subscriptions, collections.
  skills     : Capability affinities and optimization candidates.
               Use topic world.skills.affinity.<skill_id> for skill affinity facts and include skill_id, index_id, projection_policy in metadata.
               Use topic world.skills.optimization.<scope>.<candidate_key> or world.skills.optimization.new.<candidate_key> for operator-reviewed optimization candidates.

pulse — How is this person right now? Current state that changes frequently.
  chapter    : Current life phase — active work role, life stage, major transitions.
  focus      : Current priorities — this week or month's top concerns.
  mood       : Emotional and energy state — stress level, current feelings.
  blockers   : Active obstacles — external constraints, stuck points.
  intent     : Short-term intentions — what they want to do or avoid soon.

journey — What has this person been through? Accumulated experience and history.
  lessons    : Mistakes and failures — patterns that led to bad outcomes.
  patterns   : Validated approaches — rhythms and methods that work for them.
  decisions  : Key life decisions — important forks in the road.
  milestones : Achievements, abandonments, turning points.
""".strip()

LANGUAGE_RULE = """
LANGUAGE RULE: ALL written text MUST use the user's first language (check User anchors).
This applies to: PM claim text, question text, diary entries, skill descriptions, and summaries.
Preserve the user's own wording when quoting them.
""".strip()

CLAIM_TEXT_RULE = """
CLAIM TEXT RULE: PM claim text must be short, clear, explicit, and unambiguous.
- Write one precise claim, not a paragraph.
- Remove filler, hedging, duplicate context, and vague pronouns.
- Prefer compact wording that still preserves the user's meaning and evidence.
""".strip()

BOUNDARIES = """
Boundaries:
- Never store system artifacts as PM facts: run tags, dashboard state, tool traces, model/system prompt text.
- Never create facts from assistant-authored prose or proactive question text.
- If tools are insufficient for the task, explain why in your final summary.
""".strip()

CONSERVATISM_PROMPTS: dict[str, str] = {
    "low": "Be thorough. Write all durable facts you can identify from the evidence.",
    "medium": "Balance thoroughness with precision. Only write claims with clear evidence.",
    "high": "Be VERY conservative. Only preserve facts the user explicitly stated or clearly demonstrated. Prefer doing nothing over uncertain writes.",
    "creative": "This is a creative writing task. Be emotionally honest, specific, and alive.",
    "strict": "Be FAST. Only flag facts that are clearly durable and not yet stored. Do not explore.",
}
