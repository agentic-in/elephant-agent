"""Evidence packet building for reflect agents.

Constructs the user prompt that provides the agent with context about
the job, the user, and what happened in the episode.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import json
import logging
import re
from typing import Any

from packages.contracts.runtime import LearningJob
from packages.reflect import (
    aggregate_signals,
    extract_trajectory_signals,
    optimization_candidate_metadata,
    optimization_candidate_topic,
)

from packages.reflect.features.types import Feature


_INIT_TRIGGERS = frozenset({"init", "init_profile"})
_URL_PATTERN = re.compile(r"https?://[^\s<>)\"']+", re.IGNORECASE)
_BARE_DOMAIN_PATTERN = re.compile(
    r"(?<![@\w.-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|org|net|io|ai|dev|me|cn|co|app|site|xyz|edu|info)"
    r"(?:/[^\s<>)\"']*)?)",
    re.IGNORECASE,
)
_CANONICAL_TOPIC_FACETS: dict[str, frozenset[str]] = {
    "identity": frozenset({"anchor", "character", "values", "style", "body"}),
    "world": frozenset({"people", "projects", "tools", "places", "assets"}),
    "pulse": frozenset({"chapter", "focus", "mood", "blockers", "intent"}),
    "journey": frozenset({"lessons", "patterns", "decisions", "milestones"}),
}
LOGGER = logging.getLogger(__name__)


def _compact(value: object, *, limit: int = 500) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _internal_artifact_text(value: object) -> bool:
    text = " ".join(str(value or "").split()).strip().casefold()
    return any(
        marker in text
        for marker in (
            "bounded elephant sub-agent",
            "background learning agent",
            "tool.learning.result.write",
            "manual learning no-op",
            "synthetic validation",
            "run_tag=",
        )
    )


def _fact_topic(fact: Any) -> str:
    metadata = getattr(fact, "metadata", {}) if isinstance(getattr(fact, "metadata", {}), Mapping) else {}
    return str(metadata.get("topic") or "").strip()


def _profile_artifact_text(value: object, *, topic: str = "", field: str = "") -> bool:
    text = " ".join(str(value or "").split()).strip().casefold()
    topic_text = str(topic or "").casefold()
    field_text = str(field or "").casefold()
    return (
        field_text == "personal_logo"
        or "personal_logo:" in text
        or "user-avatar." in text
        or ".anchor.logo." in topic_text
    )


def _canonical_pm_topic(topic: object) -> bool:
    parts = str(topic or "").split(".")
    if len(parts) < 2:
        return False
    return parts[1] in _CANONICAL_TOPIC_FACETS.get(parts[0], frozenset())


def _skill_catalog(runtime: Any) -> tuple[Any, ...]:
    list_skills = getattr(runtime, "list_skills", None)
    if callable(list_skills):
        try:
            return tuple(list_skills())
        except Exception:
            LOGGER.debug("Failed to list skills from reflect runtime.", exc_info=True)
            return ()
    skill_runtime = getattr(runtime, "skill_runtime", None)
    if skill_runtime is not None:
        list_skills = getattr(skill_runtime, "list_skills", None)
        if callable(list_skills):
            try:
                return tuple(list_skills())
            except Exception:
                LOGGER.debug("Failed to list skills from reflect skill runtime.", exc_info=True)
                return ()
    return ()


def _skill_optimization_candidate_record(candidate: Any) -> dict[str, object]:
    metadata = optimization_candidate_metadata(candidate)
    return {
        "candidate_id": metadata.get("candidate_id", ""),
        "candidate_key": metadata.get("candidate_key", ""),
        "confidence": metadata.get("confidence", f"{getattr(candidate, 'confidence', 0.0):.2f}"),
        "index_id": metadata.get("index_id", ""),
        "occurrence_count": metadata.get("occurrence_count", "0"),
        "optimization_type": metadata.get("optimization_type", ""),
        "review_status": metadata.get("review_status", "pending"),
        "signal_type": metadata.get("signal_type", ""),
        "skill_id": metadata.get("skill_id", ""),
        "suggested_action": getattr(candidate, "suggested_action", ""),
        "summary": getattr(candidate, "summary", ""),
        "supporting_signals": list(getattr(candidate, "supporting_signals", ()) or ()),
        "target_scope": metadata.get("target_scope", "new"),
        "topic": optimization_candidate_topic(candidate),
    }


def skill_optimization_candidate_records(candidates: tuple[Any, ...]) -> tuple[dict[str, object], ...]:
    return tuple(_skill_optimization_candidate_record(candidate) for candidate in candidates)


def _skill_optimization_candidate_lines(candidates: tuple[Any, ...]) -> tuple[str, ...]:
    records = skill_optimization_candidate_records(candidates)
    lines = [
        "## Optimization Candidate Records",
        "authoritative: only the pre-aggregated records below may be persisted or applied",
        f"candidate_records: {len(records)}",
    ]
    if not records:
        return tuple(lines + ["(none)"])
    lines.extend(
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
        )
        for record in records[:10]
    )
    return tuple(lines)


def build_skill_optimization_context(runtime: Any, job: LearningJob) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[dict[str, object], ...]]:
    skills = _skill_catalog(runtime)
    signals = extract_trajectory_signals(
        runtime.repository,
        personal_model_id=job.personal_model_id,
        skills=skills,
    )
    candidates = aggregate_signals(
        signals,
        runtime.repository,
        personal_model_id=job.personal_model_id,
        skills=skills,
    )
    return signals, candidates, skill_optimization_candidate_records(candidates)


def _basic_user_anchor_lines(facts: tuple[Any, ...]) -> tuple[str, ...]:
    anchors: dict[str, str] = {}
    topic_labels = {
        "identity.anchor.name.preferred": "preferred_name",
        "identity.anchor.gender.self_description": "gender",
        "identity.character.mbti.type": "personality",
        "world.people.companion.role": "companion_role",
    }
    for fact in facts:
        topic = _fact_topic(fact)
        label = topic_labels.get(topic)
        if not label:
            # Also match by partial key
            if "name.preferred" in topic:
                label = "preferred_name"
            elif "language" in topic:
                label = "first_language"
        if not label:
            continue
        # First match per label wins — avoids duplicate preferred_name etc.
        if label in anchors:
            continue
        text = _compact(getattr(fact, "text", ""), limit=180)
        if text:
            anchors[label] = f"{label}: {text}"
    return tuple(anchors.values())


def _pm_portrait_lines(facts: tuple[Any, ...], *, limit: int = 40, canonical_only: bool = False) -> tuple[str, ...]:
    """Build a full portrait from PM facts for diary/creative features."""
    lines: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        fact_meta = dict(fact.metadata) if isinstance(fact.metadata, Mapping) else {}
        topic = fact_meta.get("topic", "")
        if "letter" in topic or "affinity" in topic:
            continue
        if canonical_only and not _canonical_pm_topic(topic):
            continue
        text = _compact(getattr(fact, "text", ""), limit=500)
        if not text or _profile_artifact_text(text, topic=str(topic)):
            continue
        key = re.sub(r"[\s，。,.：:；;]+", "", text.casefold()).removeprefix("用户")
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- [{fact.lens}] {text}")
    return tuple(lines[:limit])


def _init_profile_answer_lines(metadata: Mapping[str, Any], facts: tuple[Any, ...] = ()) -> tuple[str, ...]:
    ordered_fields = (
        "first_language",
        "learning_intensity",
        "preferred_name",
        "occupation",
        "school",
        "gender",
        "birth_date",
        "city",
        "mbti",
        "hobbies",
        "dream",
        "creative_hobby",
        "media_hobby",
        "movement_hobby",
        "relationship_mode",
        "safety_boundaries",
        "blog",
        "linkedin",
        "twitter",
        "personal_logo",
        "starter_answers",
    )
    lines: list[str] = []
    seen_fields: set[str] = set()
    for field in ordered_fields:
        value = _compact(metadata.get(f"init_{field}", ""), limit=500)
        if value and not _profile_artifact_text(value, field=field):
            lines.append(f"- {field}: {value}")
            seen_fields.add(field)

    fact_rows: list[tuple[int, str, str]] = []
    field_order = {field: index for index, field in enumerate(ordered_fields)}
    for fact in facts:
        fact_meta = dict(getattr(fact, "metadata", {}) or {}) if isinstance(getattr(fact, "metadata", {}), Mapping) else {}
        field = str(fact_meta.get("init_profile_field") or "").strip()
        if not field or field in seen_fields:
            continue
        topic = str(fact_meta.get("topic") or "").strip()
        text = _compact(getattr(fact, "text", ""), limit=500)
        if not text or _profile_artifact_text(text, topic=topic, field=field):
            continue
        if text.lower().startswith(f"{field.lower()}:"):
            text = text.split(":", 1)[1].strip()
        if field.startswith("grounding_"):
            label = str(fact_meta.get("grounding_question_title") or field).strip()
            option = str(fact_meta.get("grounding_option_label") or "").strip()
            detail = f"{text} ({option})" if option and option not in text else text
            fact_rows.append((len(ordered_fields) + 1, label, detail))
        else:
            fact_rows.append((field_order.get(field, len(ordered_fields)), field, text))
        seen_fields.add(field)

    for _, field, text in sorted(fact_rows, key=lambda row: (row[0], row[1])):
        lines.append(f"- {field}: {text}")
    return tuple(lines)


def _urls_from_text(text: object, *, limit: int = 12) -> tuple[str, ...]:
    urls: list[str] = []
    for match in _URL_PATTERN.finditer(str(text or "")):
        url = match.group(0).rstrip(".,;]")
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    if len(urls) < limit:
        for match in _BARE_DOMAIN_PATTERN.finditer(str(text or "")):
            url = match.group(1).rstrip(".,;]")
            normalized = url if url.lower().startswith(("http://", "https://")) else f"https://{url}"
            if normalized and normalized not in urls:
                urls.append(normalized)
            if len(urls) >= limit:
                break
    return tuple(urls)


def _init_profile_link_lines(metadata: Mapping[str, Any], facts: tuple[Any, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for key, value in metadata.items():
        key_text = str(key or "").lower()
        if key_text.startswith("init_") and any(marker in key_text for marker in ("blog", "link", "linkedin", "twitter", "url")):
            values.append(str(value or ""))
    for fact in facts:
        text = str(getattr(fact, "text", "") or "")
        if text:
            values.append(text)

    links: list[str] = []
    for value in values:
        for url in _urls_from_text(value):
            if url not in links:
                links.append(url)
    return tuple(f"- {url}" for url in links[:12])


def _init_evidence_use_lines(has_links: bool) -> tuple[str, ...]:
    link_line = (
        "- User-provided links are present: inspect each URL directly with web.extract/read before deriving link-based PM claims, questions, or skill affinities."
        if has_links
        else "- No user-provided links are present: do not invent a link-learning task or use web.search to look for possible personal sites."
    )
    return (
        "## Init Evidence Use",
        "- This is first-profile construction. Treat existing PM facts as raw seed evidence, not a mature profile.",
        "- Primary evidence is the Init profile answers plus the content of directly inspected User-provided links.",
        link_line,
        "- PM search is for inventory and deduplication only; it cannot open URLs or learn from a website.",
        "- Do not store local file paths, avatars, tool traces, dashboard state, prompt text, or other system artifacts.",
        "- Prefer fewer grounded, durable claims over many speculative ones. Use questions for meaningful uncertainty.",
    )


def _letter_evidence_use_lines() -> tuple[str, ...]:
    return (
        "## Letter Evidence Use Guide",
        "- Treat the portrait below as grounding evidence, not copy to paste into the letter.",
        "- Synthesize repeated facts once. Do not list the user's traits like a dashboard or psychological report.",
        "- Do not mention raw lens names, PM topics, field IDs, demographic fragments, avatar paths, or schema language.",
        "- Warmth should come from specific attention to rhythm, pressure/recovery style, current focus, values, tastes, hopes, and the tension underneath the facts.",
        "- Prefer two or three deeper observations over many shallow facts. Name what the user may be trying to protect, carry, or move toward when the evidence supports it.",
        "- Elephant may promise to remember this beginning and keep useful traces, but must not pretend a long shared history that is not in evidence.",
    )


def _build_compress_evidence(metadata: dict[str, Any]) -> str:
    """Minimal evidence for compress feature — just the conversation content.

    User identity facts are intentionally excluded — they are noise for a
    summary task and waste the compress agent's token budget.
    """
    compressed_messages = str(metadata.get("compressed_messages") or "")
    previous_summary = str(metadata.get("previous_summary") or "")
    token_budget = int(metadata.get("token_budget") or 800)
    tail_hint = str(metadata.get("tail_hint") or "")
    lines: list[str] = [
        f"Token budget: ~{token_budget} tokens",
    ]
    if previous_summary:
        lines.extend(["", "## Previous summary (for continuity)", previous_summary])
    lines.extend([
        "",
        "## Conversation to compress",
        compressed_messages or "(no content)",
    ])
    if tail_hint:
        lines.extend(["", "## Recent context (do NOT summarize, for handoff only)", tail_hint])
    return "\n".join(lines)


def _episode_turn_summary(runtime: Any, *, episode_id: str) -> tuple[str, ...]:
    """Build a concise turn-by-turn summary from episode loops/steps.

    Reads the canonical step format written by KernelStepRecorder:
      - record_input (observation): metadata.user_query
      - effective_user_query (acting): metadata.effective_user_query
      - call_model (acting): metadata.assistant_response
      - call_tool (acting): metadata.tool_name
    """
    try:
        loops = tuple(runtime.repository.list_loops(episode_id=episode_id))
    except Exception:
        LOGGER.debug("Failed to load reflect evidence episode loops.", exc_info=True)
        return ()
    if not loops:
        return ()

    # Sort loops by start time
    sorted_loops = sorted(loops, key=lambda loop: str(getattr(loop, "started_at", "") or ""))
    lines: list[str] = []
    turn_num = 0

    for loop in sorted_loops:
        try:
            steps = tuple(runtime.repository.list_steps(loop_id=loop.loop_id))
        except Exception:
            LOGGER.debug("Failed to load reflect evidence loop steps.", exc_info=True)
            continue
        if not steps:
            continue

        # Extract user query, tool stats, and assistant response from canonical step format
        user_query = ""
        assistant_response = ""
        tool_counts: dict[str, int] = {}
        skills_used: list[str] = []

        for step in sorted(steps, key=lambda s: int(getattr(s, "sequence", 0) or 0)):
            metadata = dict(step.metadata) if isinstance(getattr(step, "metadata", None), Mapping) else {}
            action = str(getattr(step, "action", "") or "")

            if action == "record_input":
                content = str(metadata.get("user_query") or "").strip()
                if content:
                    user_query = content

            elif action == "effective_user_query":
                # Prefer effective query (may include recall) over raw input
                content = str(metadata.get("effective_user_query") or metadata.get("raw_user_query") or "").strip()
                if content and not user_query:
                    user_query = content

            elif action == "call_tool":
                tool_name = str(metadata.get("tool_name") or "").strip()
                if tool_name:
                    short_name = tool_name.removeprefix("tool.")
                    tool_counts[short_name] = tool_counts.get(short_name, 0) + 1

            elif action == "call_model":
                content = str(metadata.get("assistant_response") or "").strip()
                if content:
                    assistant_response = content

        # Skip internal turns (cli.startup, learning sub-agents) with no real user input
        if not user_query and not assistant_response:
            continue
        # Also skip if the query looks like an internal system prompt
        if user_query and not assistant_response and _internal_artifact_text(user_query):
            continue

        turn_num += 1
        query_preview = user_query[:200] if user_query else "(no user input)"
        lines.append(f"Turn {turn_num}: {query_preview}")

        if tool_counts:
            total_calls = sum(tool_counts.values())
            tool_parts = [f"{name} ×{count}" if count > 1 else name for name, count in sorted(tool_counts.items(), key=lambda x: -x[1])[:6]]
            lines.append(f"  [tools: {total_calls} calls — {', '.join(tool_parts)}]")

        if skills_used:
            lines.append(f"  [skills: {', '.join(skills_used[:4])}]")

        if assistant_response:
            resp_preview = assistant_response[:300]
            lines.append(f"  assistant: {resp_preview}")

        lines.append("")

    return tuple(lines) if lines else ("(no turns found)",)


def build_evidence(
    runtime: Any,
    job: LearningJob,
    features: tuple[Feature, ...],
) -> str:
    """Build the evidence packet (user prompt) for the reflect agent."""
    feature_ids = {f.feature_id for f in features}
    metadata = dict(job.metadata) if isinstance(job.metadata, Mapping) else {}

    # Load shared context
    episode = runtime.repository.load_episode(job.episode_id)
    try:
        active_facts = tuple(
            runtime.repository.list_personal_model_facts(personal_model_id=job.personal_model_id, status="active")
        )
    except Exception:
        LOGGER.debug("Failed to load active Personal Model facts for reflect evidence.", exc_info=True)
        active_facts = ()

    anchors = _basic_user_anchor_lines(active_facts)

    # Compress has a dedicated minimal evidence format
    if feature_ids == {"compress"}:
        return _build_compress_evidence(metadata)

    lines: list[str] = [
        f"trigger: {job.trigger}",
        f"features: {', '.join(f.feature_id for f in features)}",
        "",
        "## User anchors",
        *(anchors or ("(none)",)),
    ]

    if str(job.trigger or "").strip().lower() in _INIT_TRIGGERS:
        init_answers = _init_profile_answer_lines(metadata, active_facts)
        init_links = _init_profile_link_lines(metadata, active_facts)
        portrait = _pm_portrait_lines(active_facts)
        lines.extend([
            "",
            "## Init learning objective",
            "This is the first Personal Model build after onboarding. Treat bootstrapped facts as seed evidence, not a mature profile. Build a useful first understanding from the seed facts and user-provided links; inspect links directly before inferring from them.",
            "",
            *_init_evidence_use_lines(bool(init_links)),
            "",
            "## Init profile answers",
            *(init_answers or ("(none)",)),
            "",
            "## User-provided links",
            *(init_links or ("(none)",)),
            "",
            "## Bootstrapped Personal Model facts",
            *(portrait or ("(no facts yet)",)),
        ])

    if "dream" in feature_ids:
        target_date = str(metadata.get("target_date") or "today").strip() or "today"
        user_tz = "Asia/Shanghai"
        try:
            user = runtime.inspect_user(session_id=job.episode_id)
            if user and user.timezone:
                user_tz = user.timezone
        except Exception:
            LOGGER.debug("Failed to inspect user timezone for dream reflect evidence.", exc_info=True)
            pass
        lines.extend([
            "",
            "## Dream context",
            f"target_date: {target_date}",
            f"user_timezone: {user_tz}",
        ])

    if "skill_optimization" in feature_ids:
        signals, candidates, _ = build_skill_optimization_context(runtime, job)
        lines.extend([
            "",
            "## Trajectory Signals",
            f"signals: {len(signals)}",
            *(
                f"- [{signal.signal_type}] id={signal.signal_id} {signal.summary} "
                f"(confidence={signal.confidence:.2f}, count={signal.occurrence_count})"
                for signal in signals[:15]
            ),
            "",
            "## Optimization Candidates",
            f"candidates: {len(candidates)}",
            *(f"- [{candidate.optimization_type}] {candidate.suggested_action} (confidence={candidate.confidence:.2f})" for candidate in candidates[:5]),
            "",
            *_skill_optimization_candidate_lines(candidates),
        ])

    # Episode evidence for features that learn from the supplied close packet.
    # Dream is a scheduled consolidation mode and intentionally receives no
    # episode-close packet, even when paired with question/skill maintenance.
    if (
        str(job.trigger or "").strip().lower() not in _INIT_TRIGGERS
        and "dream" not in feature_ids
        and "skill_optimization" not in feature_ids
        and feature_ids & {"pm", "questions", "skills"}
    ):
        episode_summary = _compact(getattr(episode, "exit_summary", "") if episode is not None else "", limit=700)
        turn_lines = _episode_turn_summary(runtime, episode_id=job.episode_id)
        lines.extend([
            "",
            "## Episode summary",
            *(tuple(item for item in (episode_summary,) if item) or ("(none)",)),
            "",
            "## Conversation turns",
            *(turn_lines or ("(no conversation data)",)),
        ])

    # Diary-specific context
    if "diary" in feature_ids:
        target_date = metadata.get("diary_target_date") or metadata.get("target_date", "")
        user_tz = "Asia/Shanghai"
        try:
            user = runtime.inspect_user(session_id=job.episode_id)
            if user and user.timezone:
                user_tz = user.timezone
        except Exception:
            LOGGER.debug("Failed to inspect user timezone for diary reflect evidence.", exc_info=True)
            pass
        portrait = _pm_portrait_lines(active_facts)
        lines.extend([
            "",
            "## Diary context",
            f"target_date: {target_date}",
            f"user_timezone: {user_tz}",
            "",
            "## Who this person is (active PM facts)",
            *(portrait or ("(no facts yet)",)),
        ])

    if "onboarding_letter" in feature_ids:
        target_date = str(metadata.get("target_date") or date.today().isoformat()).strip() or date.today().isoformat()
        user_tz = "Asia/Shanghai"
        try:
            user = runtime.inspect_user(session_id=job.episode_id)
            if user and user.timezone:
                user_tz = user.timezone
        except Exception:
            LOGGER.debug("Failed to inspect user timezone for onboarding letter evidence.", exc_info=True)
            pass
        portrait = _pm_portrait_lines(active_facts, limit=80, canonical_only=True)
        lines.extend([
            "",
            "## Onboarding letter context",
            f"target_date: {target_date}",
            f"user_timezone: {user_tz}",
            "letter_kind: onboarding_letter",
            "",
            *_letter_evidence_use_lines(),
            "",
            "## Grounded Personal Model portrait",
            *(portrait or ("(no facts yet)",)),
            "",
            "## Product promise to weave into the letter",
            "AI is becoming more capable, and many people quietly worry about being replaced, flattened, or forced to speed up. Do not drop a slogan. Write this as Elephant's own promise: I keep memory for the user, help them stay close to what matters, and grow beside them rather than replacing them.",
        ])

    return "\n".join(lines)
