from __future__ import annotations

from packages.contracts.runtime import (
    EvidenceRetrievalRequest,
    EvidenceRetrievalResult,
    StateFocusDecision,
    RecallEvidence,
    RecallReason,
    ResumePacket,
)

_CONTINUITY_TAGS = {"continuity", "handoff", "recovery", "resume", "scope-aware"}


def state_focus(request: EvidenceRetrievalRequest) -> StateFocusDecision | None:
    return request.state_focus


def focus_work_item_ids(request: EvidenceRetrievalRequest) -> tuple[str, ...]:
    focus = state_focus(request)
    if focus is not None and focus.focus_work_item_ids:
        return focus.focus_work_item_ids
    return request.work_item_ids


def state_focus_scope_hints(request: EvidenceRetrievalRequest) -> tuple[str, ...]:
    focus = state_focus(request)
    if focus is None:
        return ()
    hints: list[str] = []
    if focus.continuity_signal == "resume":
        hints.append("lineage")
    scope_map = {
        "episode": "episode",
        "lineage": "lineage",
        "state": "elephant",
        "personal_model": "personal_model",
    }
    mapped = scope_map.get(focus.focus_scope)
    if mapped is not None:
        hints.append(mapped)
    return tuple(dict.fromkeys(hints))


def state_focus_score_adjustments(
    request: EvidenceRetrievalRequest,
    *,
    record: RecallEvidence,
    work_item_overlap: tuple[str, ...],
) -> tuple[float, float, tuple[RecallReason, ...]]:
    focus = state_focus(request)
    if focus is None:
        return 0.0, 0.0, ()

    graph_score = 0.0
    continuity_score = 0.0
    reasons: list[RecallReason] = []
    if focus.focus_work_item_ids:
        if work_item_overlap:
            graph_score += float(len(work_item_overlap)) * 1.25
            reasons.append(
                RecallReason(
                    "state-focus.overlap",
                    f"elephant focus overlap: {','.join(work_item_overlap)}",
                    graph_score,
                )
            )
        elif record.work_item_ids:
            graph_score -= 0.75
            reasons.append(
                RecallReason(
                    "state-focus.miss",
                    "record stayed outside the resolved elephant focus",
                    -0.75,
                )
            )
    if focus.focus_family == "resume":
        if record.kind in {"procedural", "summary", "decision", "structured_turn"}:
            continuity_score += 1.1
            reasons.append(
                RecallReason(
                    "state-focus.resume",
                    f"resolved resume focus prefers durable {record.kind} evidence",
                    1.1,
                )
            )
        if _CONTINUITY_TAGS & set(record.tags):
            continuity_score += 0.5
            reasons.append(
                RecallReason(
                    "state-focus.resume-tags",
                    "resume focus boosted continuity-tagged evidence",
                    0.5,
                )
            )
    return graph_score, continuity_score, tuple(reasons)


def build_resume_packet(
    request: EvidenceRetrievalRequest,
    retrieval: EvidenceRetrievalResult,
    *,
    next_move: str = "",
    artifact_ids: tuple[str, ...] = (),
    constraint_ids: tuple[str, ...] = (),
) -> ResumePacket:
    focus = state_focus(request)
    top = retrieval.candidates[0] if retrieval.candidates else None
    evidence_ids = tuple(candidate.evidence_id for candidate in retrieval.candidates)
    if not evidence_ids and artifact_ids:
        evidence_ids = artifact_ids

    focus_ids = focus_work_item_ids(request)
    reasons: list[str] = [retrieval.scope_reason]
    if focus is not None and focus.focus_work_item_ids:
        reasons.append(f"elephant focus {', '.join(focus.focus_work_item_ids[:2])} shaped recall")
    if focus is not None and focus.continuity_signal != "none":
        reasons.append(f"elephant focus resume signal={focus.continuity_signal}")
    if focus is not None:
        reasons.append(f"elephant focus scope={focus.focus_scope}")
    opener = (
        "Resume" if focus is None or focus.focus_family == "resume" or focus.continuity_signal != "none" else "Continue"
    )
    if top is not None:
        reasons.extend(reason.detail for reason in top.reasons[:3])
        if top.replay_summary:
            reasons.append(top.replay_summary)
        focused_work_item_ids = tuple(
            work_item_id for work_item_id in focus_ids if work_item_id in top.evidence.work_item_ids
        )
        if focused_work_item_ids:
            focus_ids = focused_work_item_ids
        replay_clause = f" Replay: {top.replay_summary}." if top.replay_summary else ""
        lead_phrase = (
            "inherit the resolved focus and lead with"
            if focus is not None and focus.focus_work_item_ids
            else "lead with"
        )
        summary = (
            f"{opener} {request.episode_id} around {', '.join(focus_ids[:2]) or 'the active thread'}; "
            f"{lead_phrase} {top.evidence_id} because {', '.join(reason.detail for reason in top.reasons[:2])}.{replay_clause}"
        )
    elif evidence_ids:
        reasons.append("current-work evidence fallback kept the wake packet inspectable")
        summary = (
            f"{opener} {request.episode_id} around {', '.join(focus_ids[:2]) or 'the active thread'}; "
            f"lead with {evidence_ids[0]} because no durable evidence survived rerank and the active runtime state still carries explicit evidence refs."
        )
    else:
        summary = (
            f"{opener} {request.episode_id} with explicit scope reasoning only; "
            "no durable evidence survived rerank yet."
        )
    return ResumePacket(
        episode_id=request.episode_id,
        personal_model_id=request.personal_model_id,
        elephant_id=request.elephant_id,
        focus_work_item_ids=focus_ids,
        evidence_ids=evidence_ids,
        artifact_ids=artifact_ids,
        constraint_ids=constraint_ids,
        summary=summary,
        next_move=next_move,
        reasons=tuple(reason for reason in reasons if reason),
    )
