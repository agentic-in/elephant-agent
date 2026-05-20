"""Handlers for Personal Model Understanding tools."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from packages.understanding.personal_model_governance import ensure_valid_facet, is_protected_topic

from .handler_support import coerce_bool, coerce_int, optional_string, tool_summary
from .runtime import ToolInvocation
from .surfaces import PersonalModelUnderstandingSurface


def _string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = (value,)
    elif isinstance(value, (list, tuple)):
        items = tuple(str(item) for item in value)
    else:
        items = (str(value),)
    return tuple(item.strip() for item in items if item.strip())


def _string_mapping(value: Any) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items() if str(key).strip() and str(item).strip()}


def _looks_like_internal_learning_artifact(text: str) -> bool:
    cleaned = str(text or "").strip()
    lowered = cleaned.casefold()
    if cleaned.startswith("Question-bank signal for "):
        return True
    if cleaned.startswith("User explicitly shared ") and cleaned.endswith(("?", "？")):
        return True
    return any(
        marker in lowered
        for marker in (
            "synthetic live acceptance marker",
            "run_tag=",
            "learning agent triggered",
            "dashboard refresh",
            "system prompt",
        )
    )


def _resolve_search_status(raw: str | None) -> str:
    """Normalize the user-facing status param to a valid search status string."""
    value = (raw or "").strip().lower()
    if not value or value == "active":
        return "active"
    if value == "all":
        return "all"
    if value == "retired":
        return "retired"
    if value == "disputed":
        return "disputed"
    return value


def _check_topic_duplicate(
    surface: PersonalModelUnderstandingSurface,
    session_id: str,
    personal_model_id: str,
    lens: str,
    topic: str,
    new_text: str = "",
) -> str:
    """Check if an active claim with the same topic already exists.

    Returns a guidance string if duplicate/contradiction found, empty string otherwise.
    When the existing claim has different content, signals a contradiction
    and guides the agent to use action=correct instead of remember.
    """
    pm_id = surface._personal_model_id(session_id, personal_model_id)  # noqa: SLF001
    try:
        facts = tuple(
            surface.repository.list_personal_model_facts(
                personal_model_id=pm_id,
                lens=lens or None,
                status="active",
            )
        )
    except Exception:
        return ""
    for fact in facts:
        metadata = dict(getattr(fact, "metadata", {}) or {})
        existing_topic = str(metadata.get("topic") or "").strip()
        if existing_topic == topic:
            fact_text = str(getattr(fact, "text", "") or "").strip()
            # Detect contradiction: same topic but different content
            is_contradiction = (
                new_text
                and fact_text
                and new_text.strip().lower() != fact_text.strip().lower()
            )
            status_label = "contradiction" if is_contradiction else "duplicate_topic"
            hint_action = "This appears to be updated information" if is_contradiction else "An active claim already exists"
            return (
                f"action: remember\n"
                f"status: {status_label}\n"
                f"hint: {hint_action} at topic={topic}. "
                f"Use action=correct with ref={fact.fact_id} to update it, or choose a different topic qualifier.\n"
                f"existing_claim: [{lens}/{topic}] {fact_text[:200]}\n"
                f"existing_ref: {fact.fact_id}"
            )
    return ""


def _lines_for_claims(result: Mapping[str, Any]) -> list[str]:
    lines = [f"personal_model_id: {result.get('personal_model_id', '')}"]
    status = str(result.get("match_status") or "").strip()
    if status:
        lines.append(f"match_status: {status}")
    topics = tuple(result.get("topics") or ())
    if topics:
        lines.append(f"topics: {len(topics)}")
        for item in topics:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"- [{item.get('lens', '')}/{item.get('topic', '')}] count={item.get('claim_count', '')} policy={item.get('recall_policy', '') or '-'} updated={item.get('updated_at', '')}"
            )
            sample = str(item.get("sample_text") or "").strip()
            if sample:
                lines.append(f"  sample: {sample}")
    claims = tuple(result.get("claims") or ())
    lines.append(f"claims: {len(claims)}")
    for claim in claims:
        if not isinstance(claim, Mapping):
            continue
        lens = str(claim.get("lens") or "").strip()
        topic = str(claim.get("topic") or "").strip()
        text = str(claim.get("text") or "").strip()
        ref = str(claim.get("ref") or "").strip()
        policy = str(claim.get("recall_policy") or "").strip() or "-"
        updated = str(claim.get("updated_at") or "").strip()
        status = str(claim.get("status") or "").strip() or "-"
        protected = str(claim.get("protected") or "").strip()
        protected_suffix = f" protected={protected}" if protected else ""
        lines.append(f"- [{lens}/{topic}] ref={ref} status={status} policy={policy}{protected_suffix} updated={updated}")
        lines.append(f"  text: {text}")
        if str(claim.get("projection_policy") or "").strip() == "skill_optimization_candidate":
            candidate_parts: list[str] = []
            for key in (
                "candidate_key",
                "review_status",
                "optimization_type",
                "signal_type",
                "occurrence_count",
                "target_scope",
                "skill_id",
            ):
                value = str(claim.get(key) or "").strip()
                if value:
                    candidate_parts.append(f"{key}={value}")
            if claim.get("confidence") not in ("", None):
                candidate_parts.append(f"confidence={claim.get('confidence')}")
            if candidate_parts:
                lines.append(f"  candidate: {' '.join(candidate_parts)}")
            suggested_action = str(claim.get("suggested_action") or "").strip()
            if suggested_action:
                lines.append(f"  suggested_action: {suggested_action}")
    diagnostics = result.get("diagnostics")
    if isinstance(diagnostics, Mapping):
        reason = str(diagnostics.get("no_match_reason") or "").strip()
        if reason:
            lines.append(f"no_match_reason: {reason}")
    tip = str(result.get("search_tip") or "").strip()
    if tip:
        lines.append(f"tip: {tip}")
    suggestions = tuple(result.get("narrowing_suggestions") or ())
    if suggestions:
        lines.append(f"narrowing_suggestions: {len(suggestions)}")
        for item in suggestions[:5]:
            if isinstance(item, Mapping):
                reason = str(item.get("reason") or "").strip()
                suggestion = str(item.get("suggestion") or "").strip()
                lines.append(f"  - {suggestion}" + (f" ({reason})" if reason else ""))
    health = result.get("health_report")
    if isinstance(health, Mapping):
        lines.append(
            f"health_report: active={health.get('total_active_claims', 0)} retired={health.get('total_retired_claims', 0)} disputed={health.get('total_disputed_claims', 0)} topics={health.get('total_topics', 0)}"
        )
        for key in ("conflicting_claim_candidates", "review_claims_overdue", "cleanup_suggestions"):
            rows = tuple(health.get(key) or ())
            if rows:
                lines.append(f"{key}: {len(rows)}")
    related = tuple(result.get("related_active_claims") or ())
    if related:
        lines.append(f"related_active_claims: {len(related)}")
        for item in related[:5]:
            if isinstance(item, Mapping):
                relation = str(item.get("relation_scope") or item.get("matched_by") or "").strip()
                reason = str(item.get("relation_reason") or "").strip()
                suffix = f" relation={relation}" if relation else ""
                suffix += f" reason={reason}" if reason else ""
                lines.append(f"  - [{item.get('lens', '')}/{item.get('topic', '')}] {item.get('text', '')} ({item.get('ref', '')}){suffix}")
    return lines


def run_personal_model_search(
    invocation: ToolInvocation,
    *,
    surface: PersonalModelUnderstandingSurface | None,
) -> Mapping[str, Any]:
    if surface is None:
        raise RuntimeError("Personal Model understanding is not configured for this runtime")
    mode = optional_string(invocation.arguments.get("mode")) or "auto"
    if mode == "inventory":
        return _run_inventory_search(invocation, surface=surface)
    result = surface.search_personal_model(
        invocation.session_id,
        query=optional_string(invocation.arguments.get("query")) or "",
        lens=optional_string(invocation.arguments.get("lens")) or "",
        topic=optional_string(invocation.arguments.get("topic")) or "",
        query_variants=_string_list(invocation.arguments.get("query_variants")),
        include_diagnostics=coerce_bool(invocation.arguments.get("include_diagnostics"), default=False),
        limit=max(1, min(coerce_int(invocation.arguments.get("limit"), default=12), 30)),
        status=_resolve_search_status(optional_string(invocation.arguments.get("status"))),
        ref=optional_string(invocation.arguments.get("ref")) or "",
        personal_model_id=optional_string(invocation.arguments.get("personal_model_id")) or invocation.context.personal_model_id,
        mode=mode,
    )
    return tool_summary(
        invocation,
        "\n".join(_lines_for_claims(result)),
        side_effects=("personal_model", "search"),
    )


def _run_inventory_search(
    invocation: ToolInvocation,
    *,
    surface: PersonalModelUnderstandingSurface,
) -> Mapping[str, Any]:
    """Return lens→topic list with claim counts. No content returned."""
    personal_model_id = optional_string(invocation.arguments.get("personal_model_id")) or invocation.context.personal_model_id
    lens_filter = optional_string(invocation.arguments.get("lens")) or ""
    status_filter = _resolve_search_status(optional_string(invocation.arguments.get("status")))
    pm_id = surface._personal_model_id(invocation.session_id, personal_model_id)  # noqa: SLF001
    try:
        facts = tuple(
            surface.repository.list_personal_model_facts(
                personal_model_id=pm_id,
                status=("active", "retired", "disputed") if status_filter == "all" else status_filter,
                lens=lens_filter or None,
            )
        )
    except Exception:
        facts = ()
    # Group by lens → topic with count
    from collections import defaultdict
    inventory: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for fact in facts:
        fact_lens = str(getattr(fact, "lens", "") or "").strip()
        metadata = dict(getattr(fact, "metadata", {}) or {})
        topic = str(metadata.get("topic") or "").strip()
        if fact_lens and topic:
            inventory[fact_lens][topic] += 1
    # Format output
    lines = [f"personal_model_id: {pm_id}", f"mode: inventory", f"status: {status_filter}", f"total_claims: {len(facts)}"]
    lens_order = ["identity", "world", "pulse", "journey"]
    for lens in lens_order:
        topics = inventory.get(lens, {})
        if not topics:
            continue
        lines.append(f"\n{lens}: ({sum(topics.values())} claims)")
        for topic, count in sorted(topics.items()):
            lines.append(f"  {topic} ({count})")
    # Any lenses not in the standard order
    for lens, topics in sorted(inventory.items()):
        if lens in lens_order:
            continue
        lines.append(f"\n{lens}: ({sum(topics.values())} claims)")
        for topic, count in sorted(topics.items()):
            lines.append(f"  {topic} ({count})")
    if not inventory:
        lines.append("\n(no active claims)")
    return tool_summary(
        invocation,
        "\n".join(lines),
        side_effects=("personal_model", "search"),
    )


def _conversation_time_range(arguments: Mapping[str, Any]) -> Mapping[str, str]:
    raw = arguments.get("time_range")
    out: dict[str, str] = {}
    if isinstance(raw, Mapping):
        for key in ("expr", "start_at", "end_at", "start", "end", "timezone", "tz", "search_start_at", "search_end_at"):
            value = optional_string(raw.get(key))
            if value:
                out[key] = value
    elif isinstance(raw, str) and raw.strip():
        out["expr"] = raw.strip()
    for key in ("expr", "start_at", "end_at", "start", "end", "timezone", "tz", "search_start_at", "search_end_at"):
        value = optional_string(arguments.get(key))
        if value:
            out[key] = value
    return out


def run_conversation_search(
    invocation: ToolInvocation,
    *,
    surface: PersonalModelUnderstandingSurface | None,
) -> Mapping[str, Any]:
    if surface is None:
        raise RuntimeError("Personal Model understanding is not configured for this runtime")
    mode = optional_string(invocation.arguments.get("mode")) or "recall"
    result = surface.search_conversation(
        invocation.session_id,
        query=optional_string(invocation.arguments.get("query")) or "",
        time_range=_conversation_time_range(invocation.arguments),
        mode=mode,
        bucket=optional_string(invocation.arguments.get("bucket")) or "auto",
        preview=optional_string(invocation.arguments.get("preview")) or "anchors",
        view=optional_string(invocation.arguments.get("view")) or "conversation",
        limit=max(1, min(coerce_int(invocation.arguments.get("limit"), default=8), 30)),
        personal_model_id=optional_string(invocation.arguments.get("personal_model_id")) or invocation.context.personal_model_id,
        include_current_episode=True,
    )
    lines = [
        f"personal_model_id: {result.get('personal_model_id', '')}",
        f"scope: {result.get('scope', '')}",
        f"mode: {result.get('mode', '')}",
        f"view: {result.get('view', '')}",
        f"query: {result.get('query', '')}",
    ]
    resolved_time_range = result.get("resolved_time_range")
    if isinstance(resolved_time_range, Mapping) and resolved_time_range:
        lines.append(f"resolved_time_range: {dict(resolved_time_range)}")
    ranges = tuple(result.get("ranges") or ())
    guidance = str(result.get("guidance") or "").strip()
    if guidance:
        lines.append(f"guidance: {guidance}")
    if ranges:
        lines.append(f"ranges: {len(ranges)} bucket={result.get('bucket', '')} total={result.get('total', 0)}")
        for item in ranges[:8]:
            if not isinstance(item, Mapping):
                continue
            lines.append(f"- {item.get('range_id', '')} {item.get('start_at', '')}..{item.get('end_at', '')} score={item.get('score', 0)} count={item.get('count', 0)} by_kind={item.get('by_kind', {})}")
            time_range = item.get("time_range")
            if isinstance(time_range, Mapping) and time_range:
                lines.append(
                    f"  use: start_at={time_range.get('start_at', '')} end_at={time_range.get('end_at', '')} timezone={time_range.get('timezone', '')}"
                )
                lines.append(
                    "  recall_args: "
                    f"mode=recall start_at={time_range.get('start_at', '')} "
                    f"end_at={time_range.get('end_at', '')} timezone={time_range.get('timezone', '')} "
                    f"query={result.get('query', '')!r}"
                )
            for anchor in tuple(item.get("anchors") or ())[:2]:
                if isinstance(anchor, Mapping):
                    lines.append(f"  anchor[{anchor.get('kind', '')}]: {anchor.get('text', '')}")
                else:
                    lines.append(f"  anchor: {anchor}")
    hits = tuple(result.get("hits") or ())
    if hits:
        lines.append(f"hits: {len(hits)}")
        for hit in hits[:8]:
            if not isinstance(hit, Mapping):
                continue
            title = str(hit.get("title") or hit.get("kind") or hit.get("scope") or "history").strip()
            content = str(hit.get("content") or hit.get("text") or hit.get("summary") or "").strip()
            when = str(hit.get("when") or "").strip()
            lines.append(f"- {title}" + (f" @ {when}" if when else ""))
            if content:
                lines.append(f"  text: {content}")
    if not ranges and not hits:
        lines.append("results: 0")
    return tool_summary(invocation, "\n".join(lines), side_effects=("conversation", "search"))


def run_personal_model_inspect(
    invocation: ToolInvocation,
    *,
    surface: PersonalModelUnderstandingSurface | None,
) -> Mapping[str, Any]:
    if surface is None:
        raise RuntimeError("Personal Model understanding is not configured for this runtime")
    result = surface.inspect_personal_model(
        invocation.session_id,
        ref=optional_string(invocation.arguments.get("ref")) or "",
        topic=optional_string(invocation.arguments.get("topic")) or "",
        query=optional_string(invocation.arguments.get("query")) or "",
        limit=max(1, min(coerce_int(invocation.arguments.get("limit"), default=5), 10)),
        personal_model_id=optional_string(invocation.arguments.get("personal_model_id")) or invocation.context.personal_model_id,
    )
    lines = [
        f"personal_model_id: {result.get('personal_model_id', '')}",
        f"ref: {result.get('ref', '')}",
        f"topic: {result.get('topic', '')}",
    ]
    claim = result.get("claim")
    if isinstance(claim, Mapping):
        lines.append(f"claim: [{claim.get('lens', '')}/{claim.get('topic', '')}] {claim.get('text', '')}")
    for key in ("claims", "history", "supersedes_chain"):
        rows = tuple(result.get(key) or ())
        lines.append(f"{key}: {len(rows)}")
    return tool_summary(invocation, "\n".join(lines), side_effects=("personal_model", "inspect"))


def run_personal_model_audit(
    invocation: ToolInvocation,
    *,
    surface: PersonalModelUnderstandingSurface | None,
) -> Mapping[str, Any]:
    if surface is None:
        raise RuntimeError("Personal Model understanding is not configured for this runtime")
    result = surface.audit_personal_model(
        invocation.session_id,
        action=optional_string(invocation.arguments.get("action")) or "health",
        lens=optional_string(invocation.arguments.get("lens")) or "",
        limit=max(1, min(coerce_int(invocation.arguments.get("limit"), default=30), 100)),
        personal_model_id=optional_string(invocation.arguments.get("personal_model_id")) or invocation.context.personal_model_id,
    )
    resolved_action = str(result.get("action", "") or "")
    lines = [f"action: {resolved_action}"]
    topics = tuple(result.get("topics") or ())
    if topics:
        lines.append(f"topics: {len(topics)}")
        for item in topics:
            if isinstance(item, Mapping):
                lines.append(f"- [{item.get('lens', '')}/{item.get('topic', '')}] count={item.get('claim_count', '')}")
    health = result.get("health_report")
    if isinstance(health, Mapping):
        lines.append(
            f"health_report: active={health.get('total_active_claims', 0)} retired={health.get('total_retired_claims', 0)} disputed={health.get('total_disputed_claims', 0)} topics={health.get('total_topics', 0)}"
        )
        for key in ("conflicting_claim_candidates", "review_claims_overdue", "current_claims_stale", "retired_chain_candidates", "cleanup_suggestions"):
            rows = tuple(health.get(key) or ())
            if rows:
                lines.append(f"{key}: {len(rows)}")
        if resolved_action == "stale" and not tuple(health.get("review_claims_overdue") or ()) and not tuple(health.get("current_claims_stale") or ()):
            lines.append("stale: none")
    return tool_summary(invocation, "\n".join(lines), side_effects=("personal_model", "audit"))


def _delete_personal_model_claim(
    invocation: ToolInvocation,
    *,
    surface: PersonalModelUnderstandingSurface,
    lens: str,
    topic: str,
    ref: str,
    reason: str,
    personal_model_id: str,
) -> Mapping[str, Any]:
    pm_id = surface._personal_model_id(invocation.session_id, personal_model_id)  # noqa: SLF001
    if not ref:
        return {
            "action": "delete",
            "personal_model_id": pm_id,
            "lens": lens,
            "topic": topic,
            "retired": (),
            "status": "ambiguous",
            "no_match_hint": "delete requires a claim ref from personal_model.search to avoid removing the wrong claim",
        }
    facts = tuple(
        surface.repository.list_personal_model_facts(
            personal_model_id=pm_id,
            lens=lens or None,
            status=("active", "retired", "disputed"),
        )
    )
    target = next((fact for fact in facts if fact.fact_id == ref), None)
    if target is None:
        return {
            "action": "delete",
            "personal_model_id": pm_id,
            "lens": lens,
            "topic": topic,
            "retired": (),
            "status": "no_match",
            "no_match_hint": "no claim matched ref; search with status=all and retry with the exact ref",
        }
    metadata = dict(getattr(target, "metadata", {}) or {})
    target_topic = str(metadata.get("topic") or topic or "").strip()
    if topic and target_topic and topic != target_topic:
        return {
            "action": "delete",
            "personal_model_id": pm_id,
            "lens": lens or target.lens,
            "topic": topic,
            "retired": (),
            "status": "no_match",
            "no_match_hint": "claim ref matched but topic did not; retry with the exact topic from personal_model.search",
        }
    if is_protected_topic(target_topic, metadata):
        return {
            "action": "delete",
            "personal_model_id": pm_id,
            "lens": target.lens,
            "topic": target_topic,
            "retired": (),
            "status": "protected",
            "no_match_hint": "protected core topic cannot be deleted by agent tools; correct the content or unprotect it in the dashboard first",
            "protected_refs": (target.fact_id,),
        }
    now = datetime.now(timezone.utc)
    deleted = replace(
        target,
        status="deleted",
        metadata={
            **metadata,
            "deleted_by": "tool.personal_model.update",
            "deleted_reason": reason,
            "deleted_at": now.isoformat(),
            "understanding_status": "deleted",
        },
    )
    surface.repository.upsert_personal_model_fact(deleted)
    surface._deactivate_claim_index(personal_model_id=pm_id, fact_id=target.fact_id, status="deleted")  # noqa: SLF001
    return {
        "action": "delete",
        "personal_model_id": pm_id,
        "lens": target.lens,
        "topic": target_topic,
        "retired": (target.fact_id,),
        "status": "deleted",
    }


def run_personal_model_update(
    invocation: ToolInvocation,
    *,
    surface: PersonalModelUnderstandingSurface | None,
) -> Mapping[str, Any]:
    if surface is None:
        raise RuntimeError("Personal Model understanding is not configured for this runtime")
    source = optional_string(invocation.arguments.get("source")) or "user_said"
    text = optional_string(invocation.arguments.get("text")) or ""
    action = optional_string(invocation.arguments.get("action")) or ""
    if action in {"remember", "correct"} and not text:
        raise ValueError(f"tool.personal_model.update action={action} requires 'text'")
    if source == "learned" and action in {"remember", "correct"} and _looks_like_internal_learning_artifact(text):
        raise ValueError("learned Personal Model facts cannot store internal learning, validation, dashboard, or question-bank bookkeeping text")
    lens = optional_string(invocation.arguments.get("lens")) or ""
    topic = optional_string(invocation.arguments.get("topic")) or ""
    # Validate lens-prefixed topic format
    if topic and lens and action in {"remember", "correct"}:
        topic_parts = topic.split(".")
        if len(topic_parts) < 3:
            raise ValueError(
                f"topic must have at least 3 dot-separated segments (lens.domain.entity): {topic!r}"
            )
        if topic_parts[0] != lens:
            raise ValueError(
                f"topic first segment must match lens: topic={topic!r} but lens={lens!r}. "
                f"Use {lens}.{'.'.join(topic_parts[1:]) if len(topic_parts) > 1 else topic}"
            )
        if len(topic_parts) >= 2:
            ensure_valid_facet(lens, topic_parts[1])
    ref = optional_string(invocation.arguments.get("ref")) or ""
    reason = optional_string(invocation.arguments.get("reason")) or ""
    if action in {"delete", "restore"} and not ref:
        raise ValueError(f"tool.personal_model.update action={action} requires exact 'ref' from personal_model.search")
    personal_model_id = optional_string(invocation.arguments.get("personal_model_id")) or invocation.context.personal_model_id
    if action == "delete":
        result = _delete_personal_model_claim(
            invocation,
            surface=surface,
            lens=lens,
            topic=topic,
            ref=ref,
            reason=reason,
            personal_model_id=personal_model_id,
        )
    else:
        # Anti-duplication guard: warn if same topic already exists for remember
        if action == "remember" and topic and not ref:
            duplicate_hint = _check_topic_duplicate(surface, invocation.session_id, personal_model_id, lens, topic, new_text=text)
            if duplicate_hint:
                return tool_summary(
                    invocation,
                    duplicate_hint,
                    side_effects=("personal_model", "update"),
                )
        result = surface.update_personal_model(
            invocation.session_id,
            action=action,
            lens=lens,
            topic=topic,
            text=text,
            ref=ref,
            reason=reason,
            source=source,
            recall_policy=optional_string(invocation.arguments.get("recall_policy")) or "",
            personal_model_id=personal_model_id,
            metadata=_string_mapping(invocation.arguments.get("metadata")),
        )
    claim = result.get("claim") if isinstance(result, Mapping) else None
    lines = [
        f"action: {result.get('action', '')}",
        f"lens: {result.get('lens', (claim or {}).get('lens', ''))}",
        f"topic: {result.get('topic', (claim or {}).get('topic', ''))}",
        f"status: {result.get('status', '')}",
    ]
    if isinstance(claim, Mapping):
        lines.append(f"claim: {claim.get('text', '')}")
        lines.append(f"ref: {claim.get('ref', '')}")
        if claim.get("recall_policy"):
            lines.append(f"recall_policy: {claim.get('recall_policy', '')}")
    retired = tuple(result.get("retired") or ())
    if retired:
        lines.append(f"retired: {', '.join(str(item) for item in retired)}")
    no_match_hint = str(result.get("no_match_hint") or "").strip()
    if no_match_hint:
        lines.append(f"hint: {no_match_hint}")
    related = tuple(result.get("related_active_claims") or ())
    if related:
        lines.append(f"related_active_claims: {len(related)}")
        for item in related[:5]:
            if isinstance(item, Mapping):
                relation = str(item.get("relation_scope") or item.get("matched_by") or "").strip()
                reason = str(item.get("relation_reason") or "").strip()
                suffix = f" relation={relation}" if relation else ""
                suffix += f" reason={reason}" if reason else ""
                lines.append(f"- [{item.get('lens', '')}/{item.get('topic', '')}] {item.get('text', '')} ({item.get('ref', '')}){suffix}")
    return tool_summary(
        invocation,
        "\n".join(lines),
        side_effects=("personal_model", "update"),
    )


def run_personal_model_questions(
    invocation: ToolInvocation,
    *,
    surface: PersonalModelUnderstandingSurface | None,
) -> Mapping[str, Any]:
    if surface is None:
        raise RuntimeError("Personal Model understanding is not configured for this runtime")
    result = surface.manage_personal_model_questions(
        invocation.session_id,
        action=optional_string(invocation.arguments.get("action")) or "",
        personal_model_id=optional_string(invocation.arguments.get("personal_model_id")) or invocation.context.personal_model_id,
        question_id=optional_string(invocation.arguments.get("question_id")) or optional_string(invocation.arguments.get("ref")) or "",
        status=optional_string(invocation.arguments.get("status")) or "",
        lens=optional_string(invocation.arguments.get("lens")) or "",
        sub_lens=optional_string(invocation.arguments.get("topic")) or optional_string(invocation.arguments.get("sub_lens")) or "",
        text=optional_string(invocation.arguments.get("text")) or optional_string(invocation.arguments.get("question")) or "",
        rationale=optional_string(invocation.arguments.get("reason")) or optional_string(invocation.arguments.get("rationale")) or "",
        priority=invocation.arguments.get("priority"),
        sensitivity=optional_string(invocation.arguments.get("sensitivity")) or "",
        source=optional_string(invocation.arguments.get("source")) or "contextual",
        metadata={},
        reason=optional_string(invocation.arguments.get("reason")) or "",
        surface=optional_string(invocation.arguments.get("surface")) or "tool.personal_model.questions",
        user_response_episode_id=optional_string(invocation.arguments.get("user_response_episode_id")) or "",
        generated_fact_ids=(),
        answer=optional_string(invocation.arguments.get("answer")) or "",
        limit=max(1, min(coerce_int(invocation.arguments.get("limit"), default=10), 20)),
    )
    action = str(result.get("action") or "") if isinstance(result, Mapping) else ""
    lines = [f"action: {action}"]
    if isinstance(result, Mapping):
        questions = result.get("questions")
        if isinstance(questions, list):
            lines.append(f"questions: {len(questions)}")
            for question in questions[:5]:
                if isinstance(question, Mapping):
                    lines.append(f"- [{question.get('lens', '')}/{question.get('sub_lens', '')}] {question.get('text', '')}")
        question = result.get("question")
        if isinstance(question, Mapping):
            lines.append(f"question_id: {question.get('question_id', '')}")
            lines.append(f"status: {question.get('status', '')}")
            lines.append(f"question: {question.get('text', '')}")
        claim_update = result.get("claim_update")
        if isinstance(claim_update, Mapping):
            claim = claim_update.get("claim")
            if isinstance(claim, Mapping):
                lines.append(f"claim: {claim.get('text', '')}")
    return tool_summary(
        invocation,
        "\n".join(lines),
        side_effects=("personal_model", "questions"),
    )


__all__ = [
    "run_conversation_search",
    "run_personal_model_questions",
    "run_personal_model_search",
    "run_personal_model_update",
]
