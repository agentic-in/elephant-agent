"""PM fact lifecycle helpers for skill optimization candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .types import PersistedOptimizationCandidate, SkillOptimizationCandidate

_OPTIMIZATION_TOPIC_PREFIX = "world.skills.optimization."
_ALLOWED_REVIEW_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"approved", "rejected"},
    "approved": {"applied"},
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: object, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _metadata_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): str(value) for key, value in raw.items() if str(value or "").strip()}


def optimization_candidate_topic(candidate: SkillOptimizationCandidate) -> str:
    if candidate.target_index_id:
        return f"world.skills.optimization.{candidate.target_index_id}.{candidate.candidate_key}"
    return f"world.skills.optimization.new.{candidate.candidate_key}"


def optimization_candidate_text(candidate: SkillOptimizationCandidate) -> str:
    subject = candidate.target_skill_id or "a new skill"
    occurrence_count = _text(candidate.metadata.get("occurrence_count")) or "0"
    confidence = _text(candidate.metadata.get("confidence")) or f"{candidate.confidence:.2f}"
    return (
        f"{subject} shows a repeatable optimization opportunity. "
        f"Evidence: {candidate.summary}. "
        f"Observed in {occurrence_count} closed episodes with confidence {confidence}. "
        f"Suggested action: {candidate.suggested_action}"
    ).strip()


def optimization_candidate_metadata(
    candidate: SkillOptimizationCandidate,
    *,
    review_status: str = "pending",
    supersedes_ref: str = "",
    extra_metadata: Mapping[str, str] | None = None,
) -> dict[str, str]:
    metadata = _metadata_map(candidate.metadata)
    result = {
        **metadata,
        "topic": optimization_candidate_topic(candidate),
        "candidate_id": candidate.candidate_id,
        "candidate_key": candidate.candidate_key,
        "projection_policy": "skill_optimization_candidate",
        "optimization_type": candidate.optimization_type,
        "signal_type": _text(metadata.get("signal_type")) or "recurring_sequence",
        "occurrence_count": _text(metadata.get("occurrence_count")) or "0",
        "confidence": _text(metadata.get("confidence")) or f"{candidate.confidence:.2f}",
        "suggested_action": candidate.suggested_action,
        "review_status": review_status,
        "retention_lifecycle": "draft",
    }
    if candidate.target_skill_id:
        result["skill_id"] = candidate.target_skill_id
    if candidate.target_index_id:
        result["index_id"] = candidate.target_index_id
        result["target_scope"] = candidate.target_index_id
    if supersedes_ref:
        result["supersedes_ref"] = supersedes_ref
    if extra_metadata:
        result.update(_metadata_map(extra_metadata))
    return result


def persisted_candidate_from_fact(fact: Any) -> PersistedOptimizationCandidate | None:
    metadata = _metadata_map(getattr(fact, "metadata", {}))
    topic = _text(metadata.get("topic"))
    if not topic.startswith(_OPTIMIZATION_TOPIC_PREFIX):
        return None
    return PersistedOptimizationCandidate(
        ref=_text(getattr(fact, "fact_id", "")) or topic,
        topic=topic,
        text=_text(getattr(fact, "text", "")),
        fact_status=_text(getattr(fact, "status", "")) or "active",
        review_status=_text(metadata.get("review_status")).lower() or "pending",
        candidate_id=_text(metadata.get("candidate_id")),
        candidate_key=_text(metadata.get("candidate_key")) or topic.rsplit(".", 1)[-1],
        target_skill_id=_text(metadata.get("skill_id")) or None,
        target_index_id=_text(metadata.get("index_id")) or None,
        target_scope=_text(metadata.get("target_scope")) or None,
        optimization_type=_text(metadata.get("optimization_type")) or "update_procedure",
        signal_type=_text(metadata.get("signal_type")) or "recurring_sequence",
        occurrence_count=_safe_int(metadata.get("occurrence_count"), default=0),
        confidence=_safe_float(metadata.get("confidence"), default=_safe_float(getattr(fact, "confidence", 0.0))),
        recall_policy=_text(metadata.get("recall_policy")),
        retention_lifecycle=_text(metadata.get("retention_lifecycle")),
        committed_at=_text(getattr(fact, "committed_at", "")),
        metadata=metadata,
    )


def load_candidates(
    repository: Any,
    *,
    personal_model_id: str,
    fact_status: str | Sequence[str] = ("active", "retired", "disputed"),
) -> tuple[PersistedOptimizationCandidate, ...]:
    list_facts = getattr(repository, "list_personal_model_facts", None)
    if not callable(list_facts):
        return ()
    try:
        facts = tuple(list_facts(personal_model_id=personal_model_id, status=fact_status))
    except Exception:
        return ()
    records = [record for fact in facts if (record := persisted_candidate_from_fact(fact)) is not None]
    records.sort(key=lambda item: (item.committed_at, item.ref), reverse=True)
    return tuple(records)


def find_candidate_by_topic(
    repository: Any,
    *,
    personal_model_id: str,
    topic: str,
    fact_status: str | Sequence[str] = ("active", "retired", "disputed"),
) -> PersistedOptimizationCandidate | None:
    resolved_topic = _text(topic)
    for candidate in load_candidates(repository, personal_model_id=personal_model_id, fact_status=fact_status):
        if candidate.topic == resolved_topic:
            return candidate
    return None


def find_candidate_by_ref(
    repository: Any,
    *,
    personal_model_id: str,
    ref: str,
    fact_status: str | Sequence[str] = ("active", "retired", "disputed"),
) -> PersistedOptimizationCandidate | None:
    resolved_ref = _text(ref)
    for candidate in load_candidates(repository, personal_model_id=personal_model_id, fact_status=fact_status):
        if candidate.ref == resolved_ref:
            return candidate
    return None


def find_candidate_ref(
    repository: Any,
    *,
    personal_model_id: str,
    topic: str,
    fact_status: str | Sequence[str] = ("active", "retired", "disputed"),
) -> str:
    candidate = find_candidate_by_topic(
        repository,
        personal_model_id=personal_model_id,
        topic=topic,
        fact_status=fact_status,
    )
    return "" if candidate is None else candidate.ref


def _materially_stronger(candidate: SkillOptimizationCandidate, existing: PersistedOptimizationCandidate) -> bool:
    new_occurrence_count = _safe_int(candidate.metadata.get("occurrence_count"), default=0)
    confidence_gain = candidate.confidence - existing.confidence
    occurrence_gain = new_occurrence_count - existing.occurrence_count
    return confidence_gain >= 0.08 or occurrence_gain >= 2


def should_suppress_candidate(
    candidate: SkillOptimizationCandidate,
    existing_candidates: Sequence[PersistedOptimizationCandidate],
) -> bool:
    if not existing_candidates:
        return False
    same_candidate = [
        item
        for item in existing_candidates
        if item.candidate_key == candidate.candidate_key or item.topic == optimization_candidate_topic(candidate)
    ]
    if not same_candidate:
        return False
    latest = sorted(same_candidate, key=lambda item: (item.committed_at, item.ref), reverse=True)[0]
    if latest.review_status in {"approved", "applied"} and latest.fact_status == "active":
        return True
    if latest.review_status in {"pending", "rejected"} and latest.fact_status == "active":
        return not _materially_stronger(candidate, latest)
    if latest.review_status == "rejected":
        return not _materially_stronger(candidate, latest)
    return False


def write_optimization_candidate(
    pm_surface: Any,
    session_id: str,
    *,
    personal_model_id: str,
    candidate: SkillOptimizationCandidate,
    reason: str = "reflect skill optimization candidate",
) -> Mapping[str, Any]:
    return pm_surface.update_personal_model(
        session_id,
        action="remember",
        lens="world",
        topic=optimization_candidate_topic(candidate),
        text=optimization_candidate_text(candidate),
        reason=reason,
        source="learned",
        recall_policy="review",
        personal_model_id=personal_model_id,
        metadata=optimization_candidate_metadata(candidate),
    )


def persist_optimization_candidate(
    pm_surface: Any,
    session_id: str,
    *,
    personal_model_id: str,
    candidate: SkillOptimizationCandidate,
    reason: str = "reflect skill optimization candidate",
) -> Mapping[str, Any]:
    repository = getattr(pm_surface, "repository", None)
    existing_candidates = load_candidates(repository, personal_model_id=personal_model_id)
    if should_suppress_candidate(candidate, existing_candidates):
        existing = find_candidate_by_topic(
            repository,
            personal_model_id=personal_model_id,
            topic=optimization_candidate_topic(candidate),
        )
        return {
            "action": "remember",
            "status": "suppressed",
            "topic": optimization_candidate_topic(candidate),
            "ref": "" if existing is None else existing.ref,
            "review_status": "" if existing is None else existing.review_status,
            "candidate_key": candidate.candidate_key,
        }
    active_candidate = find_candidate_by_topic(
        repository,
        personal_model_id=personal_model_id,
        topic=optimization_candidate_topic(candidate),
        fact_status="active",
    )
    latest_candidate = find_candidate_by_topic(
        repository,
        personal_model_id=personal_model_id,
        topic=optimization_candidate_topic(candidate),
    )
    metadata = optimization_candidate_metadata(
        candidate,
        supersedes_ref="" if latest_candidate is None else latest_candidate.ref,
    )
    if active_candidate is None:
        return pm_surface.update_personal_model(
            session_id,
            action="remember",
            lens="world",
            topic=optimization_candidate_topic(candidate),
            text=optimization_candidate_text(candidate),
            reason=reason,
            source="learned",
            recall_policy="review",
            personal_model_id=personal_model_id,
            metadata=metadata,
        )
    return pm_surface.update_personal_model(
        session_id,
        action="correct",
        lens="world",
        topic=active_candidate.topic,
        text=optimization_candidate_text(candidate),
        ref=active_candidate.ref,
        reason=reason,
        source="learned",
        recall_policy="review",
        personal_model_id=personal_model_id,
        metadata=metadata,
    )


def mark_candidate_review_status(
    pm_surface: Any,
    session_id: str,
    *,
    personal_model_id: str,
    ref: str,
    review_status: str,
    reason: str = "update skill optimization candidate review status",
) -> Mapping[str, Any]:
    resolved_ref = _text(ref)
    if not resolved_ref:
        raise ValueError("mark_candidate_review_status requires exact candidate ref")
    target_status = _text(review_status).lower()
    candidate = find_candidate_by_ref(pm_surface.repository, personal_model_id=personal_model_id, ref=resolved_ref)
    if candidate is None:
        raise ValueError(f"skill optimization candidate was not found: {resolved_ref}")
    current_status = candidate.review_status or "pending"
    if target_status == current_status:
        return {
            "action": "correct",
            "status": "no_op",
            "topic": candidate.topic,
            "claim": {"ref": candidate.ref, "topic": candidate.topic, "text": candidate.text},
        }
    allowed = _ALLOWED_REVIEW_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise ValueError(f"invalid skill optimization review transition: {current_status} -> {target_status}")
    metadata = dict(candidate.metadata)
    metadata.update(
        {
            "review_status": target_status,
            "retention_lifecycle": metadata.get("retention_lifecycle") or "draft",
            "projection_policy": metadata.get("projection_policy") or "skill_optimization_candidate",
        }
    )
    return pm_surface.update_personal_model(
        session_id,
        action="correct",
        lens="world",
        topic=candidate.topic,
        text=candidate.text,
        ref=resolved_ref,
        reason=reason,
        source="learned",
        recall_policy="review",
        personal_model_id=personal_model_id,
        metadata=metadata,
    )


def _is_authored_skill(skill: Any) -> bool:
    metadata = _metadata_map(getattr(skill, "metadata", {}))
    for key in ("source_kind", "source_id"):
        if metadata.get(key) == "elephant-authored":
            return True
    for key in ("hub_reference", "install_reference", "source_reference"):
        if _text(metadata.get(key)).startswith("elephant-authored:"):
            return True
    return False


def compose_updated_instruction(skill: Any, candidate: PersistedOptimizationCandidate) -> str:
    base = _text(getattr(skill, "instruction_text", ""))
    marker = f"<!-- skill-optimization:{candidate.candidate_key} -->"
    if marker in base:
        return base
    addition = "\n".join(
        (
            marker,
            "## Reviewed optimization",
            f"- Suggested action: {candidate.metadata.get('suggested_action') or candidate.text}",
            f"- Evidence: {candidate.text}",
        )
    )
    if not base:
        return addition
    return f"{base}\n\n{addition}"


def apply_approved_optimization(
    pm_surface: Any,
    skill_surface: Any,
    session_id: str,
    *,
    personal_model_id: str,
    ref: str,
    reason: str = "apply approved skill optimization",
) -> Mapping[str, Any]:
    resolved_ref = _text(ref)
    if not resolved_ref:
        raise ValueError("apply_approved_optimization requires exact candidate ref")
    candidate = find_candidate_by_ref(pm_surface.repository, personal_model_id=personal_model_id, ref=resolved_ref)
    if candidate is None:
        raise ValueError(f"skill optimization candidate was not found: {resolved_ref}")
    if candidate.review_status != "approved":
        raise ValueError(f"apply_approved_optimization requires review_status=approved, got {candidate.review_status!r}")
    if not candidate.target_skill_id:
        return {
            "status": "approved",
            "topic": candidate.topic,
            "ref": candidate.ref,
            "skill_id": "",
            "applied": False,
            "reason": "candidate has no target authored skill",
        }
    skill = skill_surface.inspect_skill(candidate.target_skill_id, session_id=session_id)
    if not _is_authored_skill(skill):
        return {
            "status": "approved",
            "topic": candidate.topic,
            "ref": candidate.ref,
            "skill_id": candidate.target_skill_id,
            "applied": False,
            "reason": "target skill is not authored",
        }
    instruction_text = compose_updated_instruction(skill, candidate)
    update_result = skill_surface.update_authored_skill(
        candidate.target_skill_id,
        instruction_text=instruction_text,
        session_id=session_id,
    )
    candidate_result = mark_candidate_review_status(
        pm_surface,
        session_id,
        personal_model_id=personal_model_id,
        ref=resolved_ref,
        review_status="applied",
        reason=reason,
    )
    claim = candidate_result.get("claim") if isinstance(candidate_result, Mapping) else None
    return {
        "status": "applied",
        "topic": candidate.topic,
        "ref": "" if not isinstance(claim, Mapping) else _text(claim.get("ref")),
        "skill_id": candidate.target_skill_id,
        "applied": True,
        "skill_result": update_result,
        "candidate_result": candidate_result,
    }
