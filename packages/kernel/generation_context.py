"""Generation-time context enrichment for the kernel prompt.

The clean Understanding projection is intentionally small:

* stable Personal Model claims grouped by Identity, World, Pulse, Journey
* one episode-open resume note outside the cacheable prefix
* optional lens/topic-bound Personal Model question hints

Current-turn evidence recall is injected by the context layer as
`current-turn recall support`. Raw notes, profile snapshots, and style
summaries are not durable prompt truth.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

from packages.contracts.runtime import ContextBundle, PromptEnvelope

_PREFIX_CACHE_MAX = 32
_prefix_cache: dict[str, tuple[str, str]] = {}  # episode_id -> (hash, frozen_prefix)


def build_context_for_generation(
    *,
    dependencies: Any,
    request: Any,
    profile: Any,
    session: Any,
    state_focus: Any,
    work_items: tuple[Any, ...],
    recall_items: tuple[Any, ...],
    context: ContextBundle,
    decision: Any,
    plan: Any,
    continuity: Any,
) -> ContextBundle:
    if request.tool_name is not None:
        return context
    minimal_payload = _minimal_generation_payload(request)
    if minimal_payload is not None:
        return _minimal_generation_context(context, system_prompt=str(minimal_payload.get("system_prompt") or ""))
    enriched_context = context
    augment = getattr(dependencies.context, "augment_for_generation", None)
    if callable(augment):
        enriched = augment(
            session=session,
            work_items=work_items,
            recall_items=recall_items,
            context=context,
            state_focus=state_focus,
            decision=decision,
            plan=plan,
            continuity=continuity,
        )
        if isinstance(enriched, ContextBundle):
            enriched_context = enriched
    return _augment_with_system_layers(
        enriched_context,
        dependencies=dependencies,
        request=request,
        session=session,
    )


def _minimal_generation_payload(request: Any) -> dict[str, Any] | None:
    payload = getattr(request, "source_payload", {})
    if not isinstance(payload, dict):
        try:
            payload = dict(payload or {})
        except (TypeError, ValueError):
            payload = {}
    context_mode = str(payload.get("context_mode") or "").strip().lower()
    if context_mode not in {"minimal", "learning_agent"}:
        return None
    return payload


def _minimal_generation_context(context: ContextBundle, *, system_prompt: str = "") -> ContextBundle:
    system_text = str(system_prompt or "").strip()
    return replace(
        context,
        prompt_envelope=PromptEnvelope(frozen_prefix=system_text),
        rendered_prompt=system_text,
        instruction_refs=(),
        work_item_ids=(),
        evidence_refs=(),
        artifact_ids=(),
    )


def _augment_with_system_layers(
    context: ContextBundle,
    *,
    dependencies: Any,
    request: Any,
    session: Any,
) -> ContextBundle:
    storage = getattr(dependencies, "storage", None)
    if storage is None:
        return context
    envelope = context.prompt_envelope
    frozen_prefix, skill_index_section = _extract_prompt_section(
        envelope.frozen_prefix,
        "Capability Disclosure",
    )
    committed_pm_lines = _frozen_committed_pm_lines(storage, request)
    resume_lines = _episode_resume_lines(storage, request=request, session=session)
    dynamic_lines = _dynamic_system_layer_lines(storage, request)
    if not (committed_pm_lines or resume_lines or dynamic_lines or skill_index_section):
        return context

    episode_id = getattr(session, "episode_id", "") or getattr(request, "episode_id", "") or ""
    input_hash = _prefix_input_hash(frozen_prefix, committed_pm_lines, resume_lines, skill_index_section)
    cached = _prefix_cache.get(episode_id)
    if cached is not None and cached[0] == input_hash:
        frozen_prefix = cached[1]
    else:
        frozen_prefix = _build_frozen_prefix(
            frozen_prefix, committed_pm_lines, resume_lines, skill_index_section,
        )
        if episode_id:
            if len(_prefix_cache) >= _PREFIX_CACHE_MAX and episode_id not in _prefix_cache:
                oldest = next(iter(_prefix_cache))
                del _prefix_cache[oldest]
            _prefix_cache[episode_id] = (input_hash, frozen_prefix)

    prompt_envelope = PromptEnvelope(
        frozen_prefix=frozen_prefix,
        session_snapshot="",
        loop_context=_append_prompt_section(
            envelope.loop_context,
            "Current-turn recall",
            dynamic_lines,
        ),
        messages=envelope.messages,
    )
    rendered_prompt = _append_rendered_section(
        context.rendered_prompt,
        "What I know so far",
        committed_pm_lines,
    )
    rendered_prompt = _append_rendered_section(
        rendered_prompt,
        "Episode resume",
        resume_lines,
    )
    rendered_prompt = _append_rendered_section(
        rendered_prompt,
        "Current-turn context",
        dynamic_lines,
    )
    return replace(
        context,
        prompt_envelope=prompt_envelope,
        rendered_prompt=rendered_prompt,
    )


_LENS_TITLES = {
    "identity": "Identity — who they are",
    "world": "World — what is around them",
    "pulse": "Pulse — how they are right now",
    "journey": "Journey — what they have been through",
}

_LENS_DESCRIPTIONS = {
    "identity": "Core character, values, style, and body — the stable person underneath.",
    "world": "People, places, projects, tools, and assets in their life.",
    "pulse": "Current chapter, mood, focus, blockers, and intent.",
    "journey": "Lessons learned, patterns noticed, key decisions, and milestones.",
}

# Canonical facet order within each lens (for stable rendering order).
_LENS_FACET_ORDER: dict[str, tuple[str, ...]] = {
    "identity": ("anchor", "character", "values", "style", "body"),
    "world":    ("people", "projects", "tools", "places", "assets"),
    "pulse":    ("chapter", "focus", "mood", "blockers", "intent"),
    "journey":  ("lessons", "patterns", "decisions", "milestones"),
}

_KNOWN_LENSES = frozenset({"identity", "world", "pulse", "journey"})


def _topic_lens(topic: str, fallback_lens: str) -> str:
    """Derive the canonical lens from the topic prefix.

    Facts written before the lens/topic alignment was enforced may have a
    ``lens`` field that disagrees with the topic prefix (e.g. lens=world but
    topic=identity.anchor.name.preferred). The topic prefix is the authoritative
    source; fall back to the stored lens only when the topic is absent or its
    prefix is not a known lens.
    """
    if topic:
        prefix = topic.split(".")[0]
        if prefix in _KNOWN_LENSES:
            return prefix
    return fallback_lens if fallback_lens in _KNOWN_LENSES else ""


def _prefix_input_hash(
    base_prefix: str,
    pm_lines: tuple[str, ...],
    resume_lines: tuple[str, ...],
    skill_section: str,
) -> str:
    h = hashlib.sha256()
    h.update(base_prefix.encode())
    h.update(b'\x00')
    for line in pm_lines:
        h.update(len(line).to_bytes(4, "big"))
        h.update(line.encode())
    h.update(b'\x00')
    for line in resume_lines:
        h.update(len(line).to_bytes(4, "big"))
        h.update(line.encode())
    h.update(b'\x00')
    h.update(skill_section.encode())
    return h.hexdigest()


def _build_frozen_prefix(
    frozen_prefix: str,
    committed_pm_lines: tuple[str, ...],
    resume_lines: tuple[str, ...],
    skill_index_section: str,
) -> str:
    if committed_pm_lines:
        frozen_prefix = _strip_prompt_sections(
            frozen_prefix,
            "What you know about the user",
            "What you know about them",
            "What I know so far",
            "Their world",
            "Where they are right now",
            "How we work together",
            "Who they are",
            "How to be with them",
            "Their journey",
            "Their pulse",
            "Identity — who they are",
            "World — what is around them",
            "Pulse — how they are right now",
            "Journey — what they have been through",
        )
        frozen_prefix = _insert_prompt_section_after(
            frozen_prefix,
            after_heading="Your own voice",
            heading="What I know so far",
            lines=committed_pm_lines,
        )
    if skill_index_section:
        frozen_prefix = _append_raw_prompt_section(frozen_prefix, skill_index_section)
    if resume_lines:
        _existing_resume = _extract_prompt_section_content(frozen_prefix, "Episode resume")
        _has_compress_resume = bool(_existing_resume and "Reference summary:" in _existing_resume)
        if not _has_compress_resume:
            frozen_prefix = _strip_prompt_sections(frozen_prefix, "Episode resume")
            frozen_prefix = _append_prompt_section(
                frozen_prefix,
                "Episode resume",
                resume_lines,
            )
    return frozen_prefix


def invalidate_prefix_cache(episode_id: str) -> None:
    _prefix_cache.pop(episode_id, None)


def _frozen_committed_pm_lines(storage: Any, request: Any) -> tuple[str, ...]:
    """Render the committed-PM block grouped by lens then facet.

    Structure per lens (only rendered when the lens has visible facts):

        ### Identity — who they are
        Core character, values, style, and body — the stable person underneath.
        #### anchor
        - <fact>
        #### character
        - <fact>

    Facts are routed to the correct lens via their topic prefix (authoritative)
    rather than the stored lens field, which may be stale for pre-migration rows.
    Within each facet facts sort by confidence desc.
    """
    list_facts = getattr(storage, "list_personal_model_facts", None)
    if not callable(list_facts):
        return ()
    personal_model_id = str(getattr(request, "personal_model_id", "") or "")
    if not personal_model_id:
        return ()
    try:
        facts = list_facts(personal_model_id=personal_model_id, status="active")
    except Exception:
        return ()
    if not facts:
        return ()

    # by_lens_facet[lens][facet] = [fact, ...]
    by_lens_facet: dict[str, dict[str, list]] = {
        lens: {} for lens in ("identity", "world", "pulse", "journey")
    }
    for fact in facts:
        if fact.confidence < 0.6:
            continue
        metadata = dict(getattr(fact, "metadata", {}) or {})
        if not _fact_visible_in_core_prompt(fact, metadata):
            continue
        topic = str(metadata.get("topic") or "").strip()
        if topic.startswith("world.skills.affinity.") or topic.startswith("skills.affinity."):
            continue
        lens = _topic_lens(topic, getattr(fact, "lens", "") or "")
        if not lens:
            continue
        # facet = second segment of topic (e.g. identity.anchor.name → "anchor")
        parts = topic.split(".")
        facet = parts[1] if len(parts) >= 2 else "_other"
        by_lens_facet[lens].setdefault(facet, []).append(fact)

    lines: list[str] = []
    for lens in ("identity", "world", "pulse", "journey"):
        facet_map = by_lens_facet[lens]
        if not facet_map:
            continue
        lines.append(f"### {_LENS_TITLES[lens]}")
        lines.append(_LENS_DESCRIPTIONS[lens])
        # Render facets in canonical order, then any unknown facets alphabetically.
        canonical = _LENS_FACET_ORDER.get(lens, ())
        ordered_facets = [f for f in canonical if f in facet_map]
        ordered_facets += sorted(f for f in facet_map if f not in canonical)
        for facet in ordered_facets:
            facet_facts = sorted(facet_map[facet], key=lambda f: (-f.confidence, getattr(f, "fact_id", "") or getattr(f, "text", "")))
            lines.append(f"#### {facet}")
            for fact in facet_facts:
                text = _fact_prompt_text(fact)
                if text:
                    lines.append(f"- {text}")
    return tuple(lines)



def _fact_visible_in_core_prompt(fact: Any, metadata: dict[str, Any]) -> bool:
    recall_policy = str(metadata.get("recall_policy") or "").strip().lower()
    lifecycle = str(metadata.get("retention_lifecycle") or "").strip().lower()
    if recall_policy in {"temporary", "review"} or lifecycle in {"temporal", "draft", "working"}:
        return False
    text = str(getattr(fact, "text", "") or "").strip()
    if text.startswith("Question-bank signal for "):
        return False
    if text.startswith("User explicitly shared ") and text.endswith(("?", "？")):
        return False
    return True


def _fact_prompt_text(fact: Any) -> str:
    return str(getattr(fact, "text", "") or "").strip()




def _facts_for(storage: Any, personal_model_id: str) -> tuple[Any, ...]:
    list_facts = getattr(storage, "list_personal_model_facts", None)
    if not callable(list_facts):
        return ()
    try:
        return tuple(list_facts(personal_model_id=personal_model_id, status="active"))
    except Exception:
        return ()



def _episode_resume_lines(storage: Any, *, request: Any, session: Any) -> tuple[str, ...]:
    """Project the episode-open resume note outside the cacheable prefix.

    `State.current_context_note` is copied into Episode.metadata when a new
    Episode opens. Prompt generation reads that frozen episode snapshot, not the
    mutable State row, so within-Episode State writes cannot churn the provider
    prefix cache.
    """
    load_episode = getattr(storage, "load_episode", None)
    episode_id = str(getattr(session, "episode_id", "") or getattr(request, "episode_id", "") or "")
    episode = load_episode(episode_id) if episode_id and callable(load_episode) else None
    metadata = getattr(episode, "metadata", {}) if episode is not None else {}
    if not isinstance(metadata, dict):
        metadata = dict(metadata or {})
    note_text = _clean_state_field(metadata.get("opening_resume_snapshot"))
    if not note_text:
        return ()
    return (f"Resume note: {note_text}",)


# Phrases we actively filter out of state-row projections. These are
# either internal seed placeholders ("Open wake to continue...") or
# known data-decay markers ("(fake)", "elephant-core"). Keeping them in the
# frozen prompt confuses the model and reads like a config dump.
_STATE_FIELD_STOPWORDS = frozenset(
    {
        "(fake)",
        "elephant-core",
        "elephant_core",
    }
)
_STATE_FIELD_STOP_PATTERNS = (
    # Seed placeholders written by ensure_elephant_state.
    "is ready to continue the current elephant line",
    "open wake to continue the current elephant line",
    "open wake to continue",
    # Opening-prompt leakage from old state rows.
    "open the wake surface proactively",
    "very first turn of a new session",
    "treat this as one-shot in-character opening guidance",
    "say a one-line greeting",
    "say a one line greeting",
    "startup opening",
)


def _clean_state_field(raw: Any) -> str:
    """Drop known placeholder / framework-internal values from a state field."""
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.lower() in _STATE_FIELD_STOPWORDS:
        return ""
    lowered = text.casefold()
    if any(marker in lowered for marker in _STATE_FIELD_STOP_PATTERNS):
        return ""
    return text




def _dynamic_system_layer_lines(
    storage: Any,
    request: Any,
    *,
    prior_surfaced_text: str = "",
) -> tuple[str, ...]:
    del storage, request, prior_surfaced_text
    return ()



def _render_section_line(line: str) -> str:
    cleaned = str(line or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith(("### ", "- ")):
        return cleaned
    return f"- {cleaned}"


def _render_prompt_section(heading: str, lines: tuple[str, ...]) -> str:
    return "\n".join((f"### {heading}", *(_render_section_line(line) for line in lines if str(line or "").strip()))).strip()


def _append_raw_prompt_section(current: str, section: str) -> str:
    rendered = str(section or "").strip()
    if not rendered:
        return current
    existing = current.strip()
    return rendered if not existing else f"{existing}\n\n{rendered}"


def _append_prompt_section(current: str, heading: str, lines: tuple[str, ...]) -> str:
    if not lines:
        return current
    return _append_raw_prompt_section(current, _render_prompt_section(heading, lines))


def _extract_prompt_section(current: str, heading: str) -> tuple[str, str]:
    """Remove one top-level `### heading` section and return (rest, section)."""

    lines = str(current or "").splitlines()
    target = f"### {heading}".casefold()
    start: int | None = None
    end = len(lines)
    for index, line in enumerate(lines):
        if line.strip().casefold() == target:
            start = index
            break
    if start is None:
        return current, ""
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("### "):
            end = index
            break
    before = lines[:start]
    after = lines[end:]
    while before and not before[-1].strip():
        before.pop()
    while after and not after[0].strip():
        after.pop(0)
    return "\n".join((*before, "", *after)).strip(), "\n".join(lines[start:end]).strip()


def _extract_prompt_section_content(current: str, heading: str) -> str:
    """Return the body text of a `### heading` section (without the heading line itself).

    Returns empty string if the section does not exist.
    """
    lines = str(current or "").splitlines()
    target = f"### {heading}".casefold()
    start: int | None = None
    end = len(lines)
    for index, line in enumerate(lines):
        if line.strip().casefold() == target:
            start = index
            break
    if start is None:
        return ""
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("### "):
            end = index
            break
    return "\n".join(lines[start + 1:end]).strip()


def _strip_prompt_section(current: str, heading: str) -> str:
    stripped, _section = _extract_prompt_section(current, heading)
    return stripped


def _strip_prompt_sections(current: str, *headings: str) -> str:
    stripped = str(current or "")
    for heading in headings:
        while True:
            next_value, section = _extract_prompt_section(stripped, heading)
            if not section:
                break
            stripped = next_value
    return stripped


def _insert_prompt_section_after(
    current: str,
    *,
    after_heading: str,
    heading: str,
    lines: tuple[str, ...],
) -> str:
    if not lines:
        return current
    section = _render_prompt_section(heading, lines)
    existing = str(current or "").strip()
    if not existing:
        return section
    raw_lines = existing.splitlines()
    target = f"### {after_heading}".casefold()
    start: int | None = None
    insert_at = len(raw_lines)
    for index, line in enumerate(raw_lines):
        if line.strip().casefold() == target:
            start = index
            break
    if start is not None:
        insert_at = len(raw_lines)
        for index in range(start + 1, len(raw_lines)):
            if raw_lines[index].startswith("### "):
                insert_at = index
                break
    before = raw_lines[:insert_at]
    after = raw_lines[insert_at:]
    while before and not before[-1].strip():
        before.pop()
    while after and not after[0].strip():
        after.pop(0)
    return "\n".join((*before, "", section, "", *after)).strip()


def _append_rendered_section(current: str | None, heading: str, lines: tuple[str, ...]) -> str | None:
    if not lines:
        return current
    section = "\n".join((f"### {heading}", *(_render_section_line(line) for line in lines if str(line or "").strip()))).strip()
    existing = str(current or "").strip()
    return section if not existing else f"{existing}\n\n{section}"


def _compact(value: str, *, limit: int) -> str:
    compacted = " ".join(str(value).split())
    if len(compacted) <= limit:
        return compacted
    return f"{compacted[: max(limit - 1, 0)].rstrip()}..."


__all__ = ["build_context_for_generation"]
