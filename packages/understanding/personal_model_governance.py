"""Personal Model governance helpers for topic keys, related claims, and health."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from enum import StrEnum
import re
import unicodedata
from typing import Any

from packages.contracts import Fact

_TOPIC_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?")


class TopicRelation(StrEnum):
    SAME_TOPIC = "same_topic"
    SAME_ENTITY = "same_entity"
    SAME_DOMAIN = "same_domain"
    UNRELATED = "unrelated"


@dataclass(frozen=True, slots=True)
class TopicPath:
    raw: str
    domain: str
    entity: str
    aspect: str
    qualifier: tuple[str, ...] = ()

    @property
    def topic(self) -> str:
        return ".".join((self.domain, self.entity, self.aspect, *self.qualifier))

    @property
    def entity_key(self) -> str:
        return f"{self.domain}.{self.entity}"


@dataclass(frozen=True, slots=True)
class TopicPolicy:
    active_cardinality: str = "single"
    default_recall_policy: str = "review"
    review_after_days: int | None = 14
    projection_visible: bool = True


@dataclass(frozen=True, slots=True)
class ProtectedTopicPolicy:
    protection: str
    reason: str
    projection_policy: str
    facet: str


ALLOWED_FACETS: dict[str, frozenset[str]] = {
    "identity": frozenset({"anchor", "character", "values", "style", "body"}),
    "world":    frozenset({"people", "projects", "tools", "places", "assets", "skills"}),
    "pulse":    frozenset({"chapter", "focus", "mood", "blockers", "intent"}),
    "journey":  frozenset({"lessons", "patterns", "decisions", "milestones"}),
}


def ensure_valid_facet(lens: str, facet: str) -> None:
    allowed = ALLOWED_FACETS.get(lens)
    if allowed is None:
        return
    if facet not in allowed:
        raise ValueError(
            f"topic second segment must be a fixed facet for lens {lens!r}: "
            f"got {facet!r}, allowed {sorted(allowed)}"
        )


_SYSTEM_PROTECTED_TOPICS: dict[str, ProtectedTopicPolicy] = {
    # identity — who the person is (anchor, character, style, body)
    "identity.anchor.name.preferred": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "identity"),
    "identity.anchor.gender.self_description": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "identity"),
    "identity.anchor.birth.date": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "identity"),
    "identity.anchor.age.current": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "identity"),
    "identity.character.mbti.type": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "identity"),
    "identity.character.rhythm.pressure": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "rhythm"),
    "identity.character.rhythm.recovery": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "rhythm"),
    "identity.character.decision.compass": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "rhythm"),
    "identity.style.language.first": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "communication"),
    "identity.style.companion.posture": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "collaboration"),
    "identity.style.hobbies.personal": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "preference"),
    "identity.body.safety.boundary": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "safety"),
    # world — what is around the person (people, projects, tools, places, assets)
    "world.places.city.current": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "current_context"),
    # pulse — current state (chapter, focus, mood, blockers, intent)
    "pulse.chapter.work.role": ProtectedTopicPolicy("system", "init_core_profile", "core_prompt", "current_context"),
}


def clean(value: object) -> str:
    return str(value or "").strip()


def normalized_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    decomposed = unicodedata.normalize("NFKD", normalized)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def compact_text(value: object) -> str:
    normalized = normalized_text(value)
    return "".join(ch for ch in normalized if unicodedata.category(ch)[0] in {"L", "N"})


def has_cjk(text: str) -> bool:
    return any(
        "CJK" in unicodedata.name(ch, "")
        or "HIRAGANA" in unicodedata.name(ch, "")
        or "KATAKANA" in unicodedata.name(ch, "")
        for ch in text
    )


def char_ngrams(value: object, *, widths: tuple[int, ...] = (2, 3)) -> set[str]:
    text = compact_text(value)
    if not text:
        return set()
    grams: set[str] = set()
    for width in widths:
        if len(text) <= width:
            grams.add(text)
        else:
            grams.update(text[index : index + width] for index in range(0, len(text) - width + 1))
    return grams


def search_tokens(value: object) -> tuple[str, ...]:
    normalized = normalized_text(value)
    tokens: list[str] = []
    current: list[str] = []
    for ch in normalized:
        if unicodedata.category(ch)[0] in {"L", "N"} or ch in "_./:-":
            current.append(ch)
            continue
        if current:
            tokens.extend(token_variants("".join(current)))
            current = []
    if current:
        tokens.extend(token_variants("".join(current)))
    return tuple(token for token in dict.fromkeys(tokens) if token)


def token_variants(token: str) -> tuple[str, ...]:
    if not token:
        return ()
    variants: list[str] = [token]
    if has_cjk(token):
        variants.extend(char_ngrams(token, widths=(1, 2)))
    return tuple(variants)


def field_tokens(value: object, *, allow_cjk_unigram: bool = True) -> tuple[str, ...]:
    tokens = search_tokens(value)
    if allow_cjk_unigram:
        return tokens
    return tuple(token for token in tokens if not (has_cjk(token) and len(token) == 1))


def parse_topic_path(topic: object) -> TopicPath | None:
    normalized = normalized_text(topic).strip(" .")
    if not normalized or normalized == "<untitled>":
        return None
    parts = tuple(part for part in normalized.split(".") if part)
    if len(parts) < 3 or ".".join(parts) != normalized:
        return None
    if not all(_TOPIC_SEGMENT_RE.fullmatch(part) for part in parts):
        return None
    return TopicPath(raw=normalized, domain=parts[0], entity=parts[1], aspect=parts[2], qualifier=parts[3:])


def valid_topic_key(topic: object) -> str:
    parsed = parse_topic_path(topic)
    return parsed.topic if parsed is not None else ""


def ensure_valid_topic_key(topic: str) -> str:
    valid = valid_topic_key(topic)
    if not valid:
        raise ValueError("topic must use canonical dot.path format: domain.entity.aspect")
    return valid


def topic_prefix(topic: object) -> str:
    parsed = parse_topic_path(topic)
    return parsed.domain if parsed is not None else ""


def topic_entity_key(topic: object) -> str:
    parsed = parse_topic_path(topic)
    return parsed.entity_key if parsed is not None else ""


def topic_relation(left: object, right: object) -> TopicRelation:
    a = parse_topic_path(left)
    b = parse_topic_path(right)
    if a is None or b is None:
        return TopicRelation.UNRELATED
    if a.topic == b.topic:
        return TopicRelation.SAME_TOPIC
    if a.domain == b.domain and a.entity == b.entity:
        return TopicRelation.SAME_ENTITY
    if a.domain == b.domain:
        return TopicRelation.SAME_DOMAIN
    return TopicRelation.UNRELATED


def topic_relation_weight(left: object, right: object) -> float:
    return {
        TopicRelation.SAME_TOPIC: 1.0,
        TopicRelation.SAME_ENTITY: 0.75,
        TopicRelation.SAME_DOMAIN: 0.35,
        TopicRelation.UNRELATED: 0.0,
    }[topic_relation(left, right)]


def policy_for_topic(topic: object) -> TopicPolicy:
    if parse_topic_path(topic) is None:
        return TopicPolicy()
    return TopicPolicy(active_cardinality="single", default_recall_policy="review", review_after_days=14, projection_visible=True)


def is_single_active_topic(topic: object) -> bool:
    return parse_topic_path(topic) is not None


def protected_topic_policy(topic: object, metadata: Mapping[str, object] | None = None) -> ProtectedTopicPolicy | None:
    resolved = valid_topic_key(topic)
    metadata_map = dict(metadata or {})
    explicit = clean(metadata_map.get("protected") or metadata_map.get("protection"))
    if explicit == "user_unprotected":
        return None
    if explicit:
        return ProtectedTopicPolicy(
            explicit,
            clean(metadata_map.get("protected_reason")) or "user_protected_topic",
            clean(metadata_map.get("projection_policy")) or "tool_only",
            clean(metadata_map.get("facet")) or "user_protected",
        )
    return _SYSTEM_PROTECTED_TOPICS.get(resolved)


def is_protected_topic(topic: object, metadata: Mapping[str, object] | None = None) -> bool:
    return protected_topic_policy(topic, metadata) is not None


def protected_topic_metadata(topic: object, metadata: Mapping[str, object] | None = None) -> dict[str, str]:
    policy = protected_topic_policy(topic, metadata)
    if policy is None:
        return {}
    return {
        "protected": policy.protection,
        "protected_reason": policy.reason,
        "projection_policy": policy.projection_policy,
        "facet": policy.facet,
    }


def is_skill_affinity_topic(topic: object) -> bool:
    resolved = valid_topic_key(topic)
    return resolved.startswith("world.skills.affinity.") or resolved.startswith("skills.affinity.")

def skill_affinity_index_id(topic: object) -> str:
    resolved = valid_topic_key(topic)
    if resolved.startswith("world.skills.affinity."):
        return resolved[len("world.skills.affinity."):]
    if resolved.startswith("skills.affinity."):
        return resolved[len("skills.affinity."):]
    return ""


def is_skill_optimization_topic(topic: object) -> bool:
    resolved = valid_topic_key(topic)
    return resolved.startswith("world.skills.optimization.") or resolved.startswith("skills.optimization.")


def skill_optimization_scope(topic: object) -> str:
    resolved = valid_topic_key(topic)
    parts = resolved.split(".")
    if len(parts) < 4:
        return ""
    if parts[0] not in {"world", "skills"} or parts[1] != "skills" or parts[2] != "optimization":
        return ""
    return parts[3]


def skill_optimization_candidate_key(topic: object) -> str:
    resolved = valid_topic_key(topic)
    parts = resolved.split(".")
    if len(parts) < 5:
        return ""
    if parts[0] not in {"world", "skills"}:
        return ""
    if parts[1] != "skills" or parts[2] != "optimization":
        return ""
    return parts[-1]


_ALLOWED_SKILL_OPTIMIZATION_REVIEW_STATUSES = frozenset({"pending", "approved", "applied", "rejected"})
_SKILL_OPTIMIZATION_REVIEW_STATUS_ALIASES = {"new": "pending"}


def _string_metadata(metadata: Mapping[str, object] | None) -> dict[str, str]:
    return {str(key): str(value) for key, value in dict(metadata or {}).items() if clean(value)}


def canonical_skill_optimization_review_status(value: object, *, default: str = "pending") -> str:
    resolved = clean(value).lower()
    resolved = _SKILL_OPTIMIZATION_REVIEW_STATUS_ALIASES.get(resolved, resolved)
    if resolved in _ALLOWED_SKILL_OPTIMIZATION_REVIEW_STATUSES:
        return resolved
    fallback = clean(default).lower()
    fallback = _SKILL_OPTIMIZATION_REVIEW_STATUS_ALIASES.get(fallback, fallback)
    return fallback if fallback in _ALLOWED_SKILL_OPTIMIZATION_REVIEW_STATUSES else "pending"


def skill_optimization_candidate_confidence(
    metadata: Mapping[str, object] | None = None,
    *,
    default: float = 0.72,
) -> float:
    raw = clean((metadata or {}).get("confidence")) if isinstance(metadata, Mapping) else ""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(default)))
    return max(0.0, min(1.0, value))


def normalize_skill_optimization_candidate_metadata(
    topic: object,
    metadata: Mapping[str, object] | None = None,
    *,
    action: str = "",
    current_metadata: Mapping[str, object] | None = None,
) -> dict[str, str]:
    resolved_topic = valid_topic_key(topic)
    current = _string_metadata(current_metadata)
    incoming = _string_metadata(metadata)
    if not is_skill_optimization_topic(resolved_topic):
        return {**current, **incoming}

    merged = {**current, **incoming}
    candidate_key = clean(merged.get("candidate_key")) or skill_optimization_candidate_key(resolved_topic)
    scope = skill_optimization_scope(resolved_topic)
    current_status = canonical_skill_optimization_review_status(current.get("review_status"), default="pending")
    default_status = "pending" if clean(action).lower() == "remember" else current_status

    merged["projection_policy"] = "skill_optimization_candidate"
    merged["retention_lifecycle"] = "draft"
    merged["review_status"] = canonical_skill_optimization_review_status(
        merged.get("review_status"),
        default=default_status,
    )
    if candidate_key:
        merged["candidate_key"] = candidate_key
        merged.setdefault("candidate_id", f"skillopt_{candidate_key}")
    if scope and scope != "new":
        merged.setdefault("index_id", scope)
        merged.setdefault("target_scope", scope)

    return {str(key): str(value) for key, value in merged.items() if clean(value)}


def numeric_mentions(value: object) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            match.group(0).rstrip(".0") if match.group(0).endswith(".0") else match.group(0)
            for match in _NUMBER_RE.finditer(str(value or ""))
        )
    )


def text_overlap(left: object, right: object) -> float:
    left_tokens = set(field_tokens(left, allow_cjk_unigram=False))
    right_tokens = set(field_tokens(right, allow_cjk_unigram=False))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / float(min(len(left_tokens), len(right_tokens)))


def topic_similarity(left: str, right: str) -> float:
    a = normalized_text(left).replace("_", " ").replace("-", " ").replace(".", " ")
    b = normalized_text(right).replace("_", " ").replace("-", " ").replace(".", " ")
    if not a or not b or a == b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def relation_payload(
    fact: Fact,
    *,
    source_topic: str,
    source_text: str = "",
    score_hint: float = 0.0,
) -> dict[str, Any] | None:
    fact_topic = clean((fact.metadata or {}).get("topic"))
    if not fact_topic:
        return None
    relation = topic_relation(source_topic, fact_topic)
    similarity = score_hint or topic_similarity(source_topic, fact_topic)
    overlap = text_overlap(source_text, fact.text) if source_text else 0.0
    source_numbers = set(numeric_mentions(source_text))
    fact_numbers = set(numeric_mentions(fact.text))
    numeric_conflict = bool(source_numbers and fact_numbers and not source_numbers.issubset(fact_numbers))
    if relation == TopicRelation.SAME_TOPIC:
        scope, matched_by, reason, score = "same_topic", "topic_path", "same topic path", 1.0
    elif relation == TopicRelation.SAME_ENTITY:
        entity = topic_entity_key(source_topic)
        scope, matched_by, reason, score = "same_entity", "topic_path", f"same topic entity {entity}", 0.75
    elif relation == TopicRelation.SAME_DOMAIN:
        domain = topic_prefix(source_topic)
        scope, matched_by, reason, score = "same_domain", "topic_path", f"same topic domain {domain}", 0.35
    elif numeric_conflict and overlap >= 0.35:
        scope, matched_by, reason, score = (
            "numeric_conflict",
            "text_overlap_numeric_mismatch",
            "similar claim text but numeric values differ",
            max(0.72, overlap),
        )
    elif overlap >= 0.45:
        scope, matched_by, reason, score = "text_overlap", "claim_text_overlap", "claim text overlaps with selected claim", overlap
    elif similarity >= 0.55 or (source_topic and (source_topic in fact_topic or fact_topic in source_topic)):
        scope, matched_by, reason, score = "similar_topic", "topic_similarity", "topic keys are lexically similar", similarity
    else:
        return None
    return {
        "ref": fact.fact_id,
        "lens": fact.lens,
        "topic": fact_topic,
        "text": fact.text,
        "score": round(score, 3),
        "relation_scope": scope,
        "relation_reason": reason,
        "matched_by": matched_by,
    }


def similar_topic_payloads(
    facts: tuple[Fact, ...],
    *,
    lens: str = "",
    topic: str,
    text: str = "",
    exclude_refs: tuple[str, ...] = (),
    limit: int = 5,
) -> tuple[dict[str, Any], ...]:
    excluded = set(exclude_refs)
    rows: list[tuple[float, str, Fact, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        if fact.fact_id in excluded or (lens and fact.lens != lens):
            continue
        fact_topic = clean((fact.metadata or {}).get("topic"))
        if not fact_topic:
            continue
        payload = relation_payload(fact, source_topic=topic, source_text=text)
        if payload is None:
            continue
        key = (fact.lens, fact_topic)
        if key in seen:
            continue
        seen.add(key)
        rows.append((float(payload.get("score") or 0.0), fact_topic, fact, payload))
    rows.sort(key=lambda item: (-item[0], item[2].lens, item[1]))
    return tuple(item[3] for item in rows[: max(1, int(limit or 1))])


def inheritable_recall_metadata(targets: tuple[Fact, ...]) -> dict[str, str]:
    if not targets:
        return {}
    source = max(targets, key=lambda item: item.committed_at)
    metadata = dict(source.metadata or {})
    keys = (
        "recall_policy",
        "retention_lifecycle",
        "recall_time_sensitivity",
        "recall_verification",
        "review_after_days",
        "expires_at",
    )
    return {key: str(metadata[key]) for key in keys if str(metadata.get(key) or "").strip()}


def claim_payload(fact: Fact) -> dict[str, Any]:
    metadata = dict(fact.metadata or {})
    topic = clean(metadata.get("topic"))
    protection = protected_topic_policy(topic, metadata)
    confidence = float(getattr(fact, "confidence", 0.0) or 0.0)
    if is_skill_optimization_topic(topic):
        confidence = skill_optimization_candidate_confidence(metadata, default=confidence)
    payload = {
        "ref": fact.fact_id,
        "lens": fact.lens,
        "topic": topic,
        "text": fact.text,
        "status": fact.status,
        "confidence": confidence,
        "source": metadata.get("source_kind", fact.source),
        "updated_at": fact.committed_at.isoformat(),
        "reason": metadata.get("reason", ""),
        "recall_policy": metadata.get("recall_policy", ""),
        "retention_lifecycle": metadata.get("retention_lifecycle", ""),
        "last_verified_at": metadata.get("last_verified_at", ""),
        "review_after_days": metadata.get("review_after_days", ""),
        "protected": protection.protection if protection is not None else "",
        "protected_reason": protection.reason if protection is not None else "",
        "projection_policy": metadata.get("projection_policy", protection.projection_policy if protection is not None else ""),
        "facet": metadata.get("facet", protection.facet if protection is not None else ""),
    }
    if is_skill_optimization_topic(topic):
        scope = skill_optimization_scope(topic)
        payload.update(
            {
                "candidate_id": metadata.get("candidate_id", ""),
                "candidate_key": metadata.get("candidate_key", skill_optimization_candidate_key(topic)),
                "index_id": metadata.get("index_id", ""),
                "target_scope": metadata.get("target_scope", "" if scope == "new" else scope),
                "skill_id": metadata.get("skill_id", ""),
                "optimization_type": metadata.get("optimization_type", ""),
                "signal_type": metadata.get("signal_type", ""),
                "occurrence_count": metadata.get("occurrence_count", ""),
                "review_status": canonical_skill_optimization_review_status(metadata.get("review_status"), default="pending"),
                "suggested_action": metadata.get("suggested_action", ""),
            }
        )
    return payload


def topic_tree(facts: tuple[Fact, ...]) -> dict[str, dict[str, dict[str, list[str]]]]:
    tree: dict[str, dict[str, dict[str, list[str]]]] = {}
    for fact in facts:
        parsed = parse_topic_path(clean((fact.metadata or {}).get("topic")))
        if parsed is None:
            continue
        domain = tree.setdefault(parsed.domain, {})
        entity = domain.setdefault(parsed.entity, {})
        qualifiers = entity.setdefault(parsed.aspect, [])
        qualifier = ".".join(parsed.qualifier)
        if qualifier and qualifier not in qualifiers:
            qualifiers.append(qualifier)
    return {
        domain: {
            entity: {aspect: sorted(qualifiers) for aspect, qualifiers in sorted(aspects.items())}
            for entity, aspects in sorted(entities.items())
        }
        for domain, entities in sorted(tree.items())
    }


def topic_rows(facts: tuple[Fact, ...], *, limit: int) -> tuple[dict[str, Any], ...]:
    grouped: dict[tuple[str, str], list[Fact]] = {}
    for fact in facts:
        topic = clean((fact.metadata or {}).get("topic")) or "<untitled>"
        grouped.setdefault((fact.lens, topic), []).append(fact)
    rows: list[dict[str, Any]] = []
    for (lens, topic), bucket in grouped.items():
        newest = max(bucket, key=lambda item: item.committed_at)
        metadata = dict(newest.metadata or {})
        rows.append(
            {
                "lens": lens,
                "topic": topic,
                "claim_count": len(bucket),
                "updated_at": newest.committed_at.isoformat(),
                "sample_text": newest.text,
                "recall_policy": metadata.get("recall_policy", ""),
                "retention_lifecycle": metadata.get("retention_lifecycle", ""),
                **protected_topic_metadata(topic, metadata),
            }
        )
    rows.sort(key=lambda item: (str(item["lens"]), str(item["topic"])))
    return tuple(rows[: max(1, int(limit or 1))])


def related_claims_for_selection(
    facts: tuple[Fact, ...],
    selected: tuple[Fact, ...],
    *,
    limit: int = 8,
) -> tuple[dict[str, Any], ...]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for fact in selected:
        topic = clean((fact.metadata or {}).get("topic"))
        if not topic:
            continue
        for item in similar_topic_payloads(facts, topic=topic, text=fact.text, exclude_refs=(fact.fact_id,), limit=limit):
            ref = str(item.get("ref") or "")
            if not ref or ref in seen:
                continue
            seen.add(ref)
            out.append(item)
            if len(out) >= limit:
                return tuple(out)
    return tuple(out)


def narrowing_suggestions(
    selected: tuple[Fact, ...],
    *,
    mode: str,
    lens: str | None,
    topic: str,
    limit: int,
) -> tuple[dict[str, str], ...]:
    if not selected:
        return ()
    topics = tuple(dict.fromkeys(clean((fact.metadata or {}).get("topic")) for fact in selected if clean((fact.metadata or {}).get("topic"))))
    lenses = tuple(dict.fromkeys(fact.lens for fact in selected if fact.lens))
    ambiguous = len(selected) >= min(max(limit, 1), 5) or len(topics) >= 3 or len(lenses) >= 2
    if not ambiguous:
        return ()
    reason = f"returned {len(selected)} active claims"
    if topics:
        reason += f" across {len(topics)} topics"
    suggestions = [
        {"reason": reason, "suggestion": "retry with topic or ref when locating one known claim"},
        {"reason": "verification needs a precise target", "suggestion": "retry tool.personal_model.search with an exact topic, ref, or claim phrase"},
    ]
    if not lens and lenses:
        suggestions.append({"reason": f"matches span lenses: {', '.join(lenses[:4])}", "suggestion": "add lens to constrain the owner surface"})
    if not topic and topics:
        suggestions.append({"reason": "multiple topic keys matched", "suggestion": f"add topic, e.g. {', '.join(topics[:4])}"})
    return tuple(suggestions)


def _facts_by_topic_key(facts: tuple[Fact, ...]) -> dict[tuple[str, str], list[Fact]]:
    grouped: dict[tuple[str, str], list[Fact]] = {}
    for fact in facts:
        topic = clean((fact.metadata or {}).get("topic")) or "<untitled>"
        grouped.setdefault((fact.lens, valid_topic_key(topic) or topic), []).append(fact)
    return grouped


def _numeric_conflict_payloads(facts: tuple[Fact, ...]) -> tuple[dict[str, Any], ...]:
    conflicts: list[dict[str, Any]] = []
    grouped = _facts_by_topic_key(tuple(fact for fact in facts if fact.status == "active"))
    for (lens, topic_key), bucket in grouped.items():
        if len(bucket) < 2:
            continue
        for index, left in enumerate(bucket):
            left_numbers = set(numeric_mentions(left.text))
            if not left_numbers:
                continue
            for right in bucket[index + 1 :]:
                right_numbers = set(numeric_mentions(right.text))
                if not right_numbers or left_numbers == right_numbers:
                    continue
                same_raw_topic = clean((left.metadata or {}).get("topic")) == clean((right.metadata or {}).get("topic"))
                if not same_raw_topic and text_overlap(left.text, right.text) < 0.25:
                    continue
                conflicts.append(
                    {
                        "lens": lens,
                        "topic_key": topic_key,
                        "refs": (left.fact_id, right.fact_id),
                        "topics": (clean((left.metadata or {}).get("topic")), clean((right.metadata or {}).get("topic"))),
                        "values": (tuple(sorted(left_numbers)), tuple(sorted(right_numbers))),
                        "reason": "active claims share a topic key but contain different numeric values",
                    }
                )
    return tuple(conflicts)


def _parse_datetime_value(value: object) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def personal_model_health_report(facts: tuple[Fact, ...], *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    active = tuple(fact for fact in facts if fact.status == "active")
    retired = tuple(fact for fact in facts if fact.status == "retired")
    disputed = tuple(fact for fact in facts if fact.status == "disputed")
    active_topics = tuple(dict.fromkeys(clean((fact.metadata or {}).get("topic")) or "<untitled>" for fact in active))
    prefixes: dict[str, int] = {}
    for topic in active_topics:
        prefixes[topic_prefix(topic) or "<untitled>"] = prefixes.get(topic_prefix(topic) or "<untitled>", 0) + 1
    conflicts = _numeric_conflict_payloads(facts)
    review_overdue: list[dict[str, str]] = []
    current_stale: list[dict[str, str]] = []
    without_policy: list[dict[str, str]] = []
    without_reason: list[dict[str, str]] = []
    for fact in active:
        metadata = dict(fact.metadata or {})
        topic = clean(metadata.get("topic")) or "<untitled>"
        policy = clean(metadata.get("recall_policy"))
        reason = clean(metadata.get("reason") or metadata.get("evidence"))
        if not policy:
            without_policy.append({"ref": fact.fact_id, "lens": fact.lens, "topic": topic})
        if not reason:
            without_reason.append({"ref": fact.fact_id, "lens": fact.lens, "topic": topic})
        verified = _parse_datetime_value(metadata.get("last_verified_at") or metadata.get("verified_at")) or fact.committed_at
        age_days = max(0, (current - verified).days)
        if policy == "review":
            try:
                review_days = int(str(metadata.get("review_after_days") or "14"))
            except ValueError:
                review_days = 14
            if age_days > review_days:
                review_overdue.append({"ref": fact.fact_id, "lens": fact.lens, "topic": topic, "age_days": str(age_days)})
        if policy == "current" and age_days > 30:
            current_stale.append({"ref": fact.fact_id, "lens": fact.lens, "topic": topic, "age_days": str(age_days)})
    retired_chain_candidates = tuple(
        {
            "lens": lens,
            "topic": topic,
            "retired_count": str(len(bucket)),
            "refs": tuple(fact.fact_id for fact in sorted(bucket, key=lambda item: item.committed_at, reverse=True)[:8]),
            "reason": "topic has a long retired chain; keep for audit, but review whether old links still need dashboard prominence",
        }
        for (lens, topic), bucket in sorted(_facts_by_topic_key(retired).items(), key=lambda item: (-len(item[1]), item[0][0], item[0][1]))
        if len(bucket) >= 5
    )
    cleanup_suggestions = [
        {
            "kind": "numeric_conflict",
            "refs": tuple(item.get("refs") or ()),
            "reason": item.get("reason", "numeric conflict"),
            "recommended_action": "verify the current value, then correct/forget stale refs",
        }
        for item in conflicts[:8]
    ] + [
        {
            "kind": "long_retired_chain",
            "refs": tuple(item.get("refs") or ()),
            "reason": item.get("reason", "long retired chain"),
            "recommended_action": "inspect the retired chain before compacting or hiding old history",
        }
        for item in retired_chain_candidates[:8]
    ]
    return {
        "total_active_claims": len(active),
        "total_retired_claims": len(retired),
        "total_disputed_claims": len(disputed),
        "total_topics": len(active_topics),
        "topics_by_prefix": dict(sorted(prefixes.items())),
        "duplicate_topic_candidates": (),
        "duplicate_claim_candidates": tuple(cleanup_suggestions),
        "conflicting_claim_candidates": conflicts,
        "review_claims_overdue": tuple(review_overdue),
        "current_claims_stale": tuple(current_stale),
        "claims_without_recall_policy": tuple(without_policy),
        "claims_without_reason": tuple(without_reason),
        "retired_chain_candidates": retired_chain_candidates,
        "cleanup_suggestions": tuple(cleanup_suggestions),
    }
