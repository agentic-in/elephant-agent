"""Aggregation of deterministic tool-trajectory signals into skill candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha1
from typing import Any

from .lifecycle import load_candidates, should_suppress_candidate
from .types import SkillOptimizationCandidate, ToolTrajectorySignal


def _text(value: object) -> str:
    return str(value or "").strip()


def _normalized_token(value: object) -> str:
    cleaned = "".join(ch if str(ch).isalnum() else "_" for ch in _text(value).lower())
    return "_".join(part for part in cleaned.split("_") if part)


def _load_active_affinity_map(repository: Any, *, personal_model_id: str) -> dict[str, tuple[str, str]]:
    list_facts = getattr(repository, "list_personal_model_facts", None)
    if not callable(list_facts):
        return {}
    try:
        facts = tuple(list_facts(personal_model_id=personal_model_id, status="active"))
    except Exception:
        return {}
    affinity_map: dict[str, tuple[str, str]] = {}
    for fact in facts:
        metadata = dict(getattr(fact, "metadata", {}) or {})
        topic = _text(metadata.get("topic"))
        if not topic.startswith("world.skills.affinity.") and not topic.startswith("skills.affinity."):
            continue
        skill_id = _text(metadata.get("skill_id"))
        index_id = _text(metadata.get("index_id")) or topic.rsplit(".", 1)[-1]
        if not skill_id and not index_id:
            continue
        for key in {skill_id, index_id, _normalized_token(skill_id), _normalized_token(index_id)} - {""}:
            affinity_map[key] = (skill_id or index_id, index_id or _normalized_token(skill_id))
    return affinity_map


def load_existing_candidate_statuses(repository: Any, *, personal_model_id: str) -> dict[str, str]:
    """Load existing optimization candidate keys and their latest review statuses."""

    statuses: dict[str, str] = {}
    for record in load_candidates(repository, personal_model_id=personal_model_id):
        statuses.setdefault(record.candidate_key, record.review_status)
    return statuses


def build_candidate_key(
    optimization_type: str,
    signal: ToolTrajectorySignal,
    *,
    target_index_id: str | None,
) -> str:
    fingerprint = sha1(
        "|".join(
            [
                optimization_type,
                _text(target_index_id) or "new",
                signal.signal_type,
                ",".join(signal.tool_names),
            ]
        ).encode("utf-8")
    ).hexdigest()[:8]
    return f"{optimization_type}_{fingerprint}"


def _skill_match_score(skill: Any, signal: ToolTrajectorySignal) -> float:
    instruction_text = _text(getattr(skill, "instruction_text", "")).lower()
    if not instruction_text:
        return 0.0
    matches = sum(1 for tool_name in signal.tool_names if _text(tool_name).lower() in instruction_text)
    if matches <= 0:
        return 0.0
    return matches / float(max(1, len(signal.tool_names)))


def _resolve_target_skill(
    signal: ToolTrajectorySignal,
    *,
    affinity_map: Mapping[str, tuple[str, str]],
    skills: Sequence[Any],
) -> tuple[str | None, str | None]:
    best_match: tuple[float, str | None, str | None] = (0.0, None, None)
    for skill in skills:
        skill_id = _text(getattr(skill, "skill_id", ""))
        if not skill_id:
            continue
        normalized_skill_id = _normalized_token(skill_id)
        affinity = (
            affinity_map.get(skill_id)
            or affinity_map.get(normalized_skill_id)
            or affinity_map.get(_normalized_token(getattr(skill, "display_name", "")))
        )
        score = _skill_match_score(skill, signal)
        if affinity is not None:
            score += 0.2
        if score > best_match[0]:
            target_skill_id = affinity[0] if affinity is not None else skill_id
            target_index_id = affinity[1] if affinity is not None else normalized_skill_id
            best_match = (score, target_skill_id, target_index_id)
    if best_match[0] <= 0.0:
        return None, None
    return best_match[1], best_match[2]


def _optimization_type_for(signal: ToolTrajectorySignal, *, target_skill_id: str | None) -> str:
    if target_skill_id is None:
        return "create_new"
    return {
        "recurring_sequence": "update_procedure",
        "error_recovery": "add_error_handling",
        "tool_combination": "add_combination_guide",
        "skill_gap": "update_triggers",
        "outdated_pattern": "update_tool_refs",
    }.get(signal.signal_type, "update_procedure")


def _summary_for(signal: ToolTrajectorySignal, *, optimization_type: str, target_skill_id: str | None) -> tuple[str, str]:
    if optimization_type == "create_new":
        return (
            signal.summary,
            f"Create a new skill capturing the repeated pattern: {', '.join(signal.tool_names)}.",
        )
    if optimization_type == "add_error_handling":
        return (
            signal.summary,
            f"Update {target_skill_id} with an explicit recovery path for {signal.tool_names[0]} failures.",
        )
    if optimization_type == "add_combination_guide":
        return (
            signal.summary,
            f"Extend {target_skill_id} with a combination guide for {', '.join(signal.tool_names)}.",
        )
    return (
        signal.summary,
        f"Update {target_skill_id} to encode the repeated tool sequence {' -> '.join(signal.tool_names)}.",
    )


def aggregate_signals(
    signals: Sequence[ToolTrajectorySignal],
    repository: Any,
    *,
    personal_model_id: str,
    skills: Sequence[Any] = (),
    max_candidates: int = 5,
) -> tuple[SkillOptimizationCandidate, ...]:
    """Aggregate raw signals into stable candidate records."""

    if not signals:
        return ()
    affinity_map = _load_active_affinity_map(repository, personal_model_id=personal_model_id)
    existing_candidates = load_candidates(repository, personal_model_id=personal_model_id)
    candidates: dict[str, SkillOptimizationCandidate] = {}
    for signal in signals:
        target_skill_id, target_index_id = _resolve_target_skill(signal, affinity_map=affinity_map, skills=skills)
        optimization_type = _optimization_type_for(signal, target_skill_id=target_skill_id)
        candidate_key = build_candidate_key(optimization_type, signal, target_index_id=target_index_id)
        summary, suggested_action = _summary_for(
            signal,
            optimization_type=optimization_type,
            target_skill_id=target_skill_id,
        )
        candidate_id = f"cand_{sha1(candidate_key.encode('utf-8')).hexdigest()[:12]}"
        metadata = {
            "signal_type": signal.signal_type,
            "occurrence_count": str(signal.occurrence_count),
            "confidence": f"{signal.confidence:.2f}",
            "review_status": "pending",
            "suggested_action": suggested_action,
        }
        if target_index_id:
            metadata["target_scope"] = target_index_id
        candidate = SkillOptimizationCandidate(
            candidate_id=candidate_id,
            target_skill_id=target_skill_id,
            target_index_id=target_index_id,
            optimization_type=optimization_type,
            supporting_signals=(signal.signal_id,),
            confidence=signal.confidence,
            summary=summary,
            suggested_action=suggested_action,
            candidate_key=candidate_key,
            metadata=metadata,
        )
        if should_suppress_candidate(candidate, existing_candidates):
            continue
        existing = candidates.get(candidate_key)
        if existing is None or candidate.confidence > existing.confidence:
            candidates[candidate_key] = candidate
    ordered = sorted(candidates.values(), key=lambda item: (-item.confidence, item.candidate_key))
    return tuple(ordered[: max(0, max_candidates)])
