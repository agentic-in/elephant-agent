"""Context runtime retrieval, replay, and scoring helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

from packages.contracts.layers import Episode
from packages.contracts.runtime import (
    StateFocusDecision,
    RecallEvidence,
    StructuredTurnSlot,
)


from .runtime_types import (
    ContextBudgetPlan,
    ContextRetrievalRequest,
    RecallEvidence,
    StructuredTurnSlot,
)


def _budget_for(budgets: ContextBudgetPlan, layer_name: str) -> int:
    allocation = budgets.allocation_for(layer_name)
    return allocation.allocated_tokens if allocation else 0


def _work_item_line(work_item: object) -> str:
    """Human-readable work-item line for prompt injection.

    Intentionally omits the work_item_id and evidence_refs ids: those are
    runtime bookkeeping. The model only needs title + status/priority to
    reason about active work. ids stay in audit_refs for telemetry.
    """
    return f"{work_item.title} [{work_item.status}/{work_item.priority}]"


def _evidence_line(evidence: RecallEvidence) -> str:
    """Human-readable evidence line for prompt injection.

    Drops evidence_ref / work_item_ids / tag set. Kind is rendered as a
    short natural label prefix via ``_evidence_kind_prose`` so the reader
    can tell a "decision" from a runtime signal without seeing raw
    ``[kind]`` taxonomic labels.
    """
    kind_label = _evidence_kind_prose(str(getattr(evidence, "kind", "") or ""))
    if kind_label:
        return f"{kind_label}: {evidence.content}"
    return str(evidence.content)


_MEMORY_KIND_PROSE = {
    "decision": "Decision",
    "observation": "Runtime signal",
    "correction": "Correction",
    "preference": "Preference",
    "knowledge": "What you know",
    "relationship": "Relationship note",
    "procedural": "Procedure",
    "style": "Style note",
    "core": "Core identity note",
    "episodic_index": "Episode note",
    "episodic": "Episode note",
    "work_item": "Work note",
    "continuity": "Continuity note",
}


def _evidence_kind_prose(kind: str) -> str:
    cleaned = str(kind or "").strip().lower()
    if not cleaned:
        return ""
    if cleaned in _MEMORY_KIND_PROSE:
        return _MEMORY_KIND_PROSE[cleaned]
    return cleaned.replace("_", " ").replace("-", " ").capitalize()


def _looks_like_profile_evidence_line(line: str) -> bool:
    normalized = " ".join(str(line or "").casefold().split())
    if not normalized:
        return False
    return normalized.startswith(
        (
            "what you know: preferred name",
            "what you know: first language",
            "what you know: city/timezone context",
            "what you know: day-to-day context",
            "what you know: care context",
        )
    )


def _content_dedup_key(text: str) -> str:
    """Normalize content for cross-section dedup.

    Prevents same evidence showing under Still-steady / Pulled-up-just-now /
    generation_context all at once.
    """
    from hashlib import blake2b as _blake2b

    compact_text = " ".join(str(text or "").casefold().split())
    while compact_text and compact_text[-1] in ".,;:!?":
        compact_text = compact_text[:-1].rstrip()
    if not compact_text:
        return ""
    return _blake2b(compact_text.encode("utf-8"), digest_size=12).hexdigest()


def _state_focus_focus_work_item_ids(
    work_items: tuple[...],
    *,
    state_focus: StateFocusDecision | None,
) -> tuple[str, ...]:
    if state_focus is None or not state_focus.focus_work_item_ids:
        return ()
    work_item_ids = {work_item.work_item_id for work_item in work_items}
    return tuple(work_item_id for work_item_id in state_focus.focus_work_item_ids if work_item_id in work_item_ids)


def _snapshot_work_items(
    work_items: tuple[...],
    *,
    state_focus: StateFocusDecision | None,
) -> tuple[...]:
    if state_focus is None:
        return work_items
    focus_ids = _state_focus_focus_work_item_ids(work_items, state_focus=state_focus)
    work_item_index = {work_item.work_item_id: work_item for work_item in work_items}
    focused = tuple(work_item_index[work_item_id] for work_item_id in focus_ids)
    if state_focus.focus_scope == "personal_model" and not focused:
        return ()
    if focused:
        if state_focus.context_budget == "broad":
            focused_ids = set(focus_ids)
            tail = tuple(work_item for work_item in work_items if work_item.work_item_id not in focused_ids)
            return focused + tail
        return focused
    return work_items


def _state_focus_budget_multiplier(state_focus: StateFocusDecision | None) -> float:
    if state_focus is None:
        return 1.0
    if state_focus.context_budget == "narrow":
        return 0.75
    if state_focus.context_budget == "broad":
        return 1.35
    return 1.0


def _select_steady_recall_items(
    recall_items: tuple[RecallEvidence, ...],
    *,
    session: Episode,
    work_items: tuple[...],
    state_focus: StateFocusDecision | None = None,
    limit: int = 3,
) -> tuple[RecallEvidence, ...]:
    if not recall_items:
        return ()
    scored = sorted(
        recall_items,
        key=lambda evidence: (
            -_context_evidence_score(
                evidence,
                session=session,
                work_items=work_items,
                state_focus=state_focus,
                layer_name="steady",
            ),
            -(evidence.created_at.timestamp() if evidence.created_at is not None else 0.0),
            evidence.evidence_id,
        ),
    )
    selected = scored[:limit]
    return tuple(
        sorted(
            selected,
            key=lambda evidence: (
                evidence.created_at.timestamp() if evidence.created_at is not None else 0.0,
                evidence.evidence_id,
            ),
        )
    )


def _steady_recall_refs(
    recall_items: tuple[RecallEvidence, ...],
    *,
    session: Episode,
    work_items: tuple[...],
    state_focus: StateFocusDecision | None = None,
) -> tuple[str, ...]:
    return tuple(
        evidence.evidence_id
        for evidence in _select_steady_recall_items(
            recall_items,
            session=session,
            work_items=work_items,
            state_focus=state_focus,
        )
    )


def _work_item_trace_reason(work_items: tuple[...]) -> str:
    if not work_items:
        return "no active elephant work items were available"
    selected = ", ".join(
        f"{work_item.work_item_id}({work_item.status}/{work_item.priority})" for work_item in work_items[:3]
    )
    tail = " ..." if len(work_items) > 3 else ""
    return f"active elephant work items stayed visible: {selected}{tail}"


def _derived_source_refs(prefix: str, items: tuple[str, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for index, item in enumerate(items, start=1):
        head = item.split(":", 1)[0].strip().lower().replace(" ", "-")
        if head and all(ch.isalnum() or ch in {"-", "_", "."} for ch in head):
            refs.append(head)
        else:
            refs.append(f"{prefix}:{index}")
    return tuple(refs)


def _loop_context_trace_reason(session: Episode, recent_loop_context: tuple[str, ...]) -> str:
    if recent_loop_context:
        return f"{len(recent_loop_context)} live Loop context item(s) keep the current exchange request-time only"
    if session.interruption_state:
        return f"no request-time Loop context was supplied, so the frame leans on {session.interruption_state}"
    return "no request-time Loop context was supplied, so the frame leans on durable snapshot state"


def _session_snapshot_trace_reason(
    session: Episode,
    work_items: tuple[...],
    recall_items: tuple[RecallEvidence, ...],
    *,
    state_focus: StateFocusDecision | None,
    profile_snapshot_refs: tuple[str, ...],
    steady_recall_items: tuple[RecallEvidence, ...],
    retrieval_requests: tuple[ContextRetrievalRequest, ...],
    summary_requests: tuple[ContextSummaryRequest, ...],
) -> str:
    """Build the rationale text for the session-snapshot source trace.

    Counts are fine; concrete ids (evidence_ref, work_item_id, focus ids) are
    intentionally omitted so the rationale stays safe to ship anywhere,
    including into audit logs that may later be rendered near the prompt.
    """
    snapshot_work_items = _snapshot_work_items(work_items, state_focus=state_focus)
    work_item_count = len(snapshot_work_items)
    retrieved_count = sum(len(request.evidence_refs) for request in retrieval_requests)
    pieces = [
        f"profile slice kept {len(profile_snapshot_refs) or 1} durable projection(s)",
        f"work slice kept {work_item_count} active elephant work item(s)",
        f"evidence slice kept {retrieved_count} retrieved evidence record(s)",
    ]
    if session.interruption_state:
        pieces.append(f"continuity recovery stayed explicit via {session.interruption_state}")
    if steady_recall_items:
        pieces.append(f"steady continuity carried {len(steady_recall_items)} evidence record(s)")
    if summary_requests:
        pieces.append("the session snapshot was compacted instead of expanding into a blind recency slice")
    if state_focus is not None:
        pieces.append(f"elephant focus scope={state_focus.focus_scope} budget={state_focus.context_budget}")
        if state_focus.focus_scope == "personal_model" and work_item_count == 0:
            pieces.append("personal_model scope suppressed unrelated work items")
    if not recall_items:
        pieces.append("no durable evidence records were available")
    return "; ".join(pieces)


def _request_attachment_trace_reason(artifacts: tuple[str, ...]) -> str:
    if artifacts:
        return f"{len(artifacts)} request/runtime attachment(s) stayed visible for request-time steering"
    return "no request attachments were needed"


def _session_snapshot_lines(
    *,
    session: Episode,
    profile_snapshot_refs: tuple[str, ...],
    work_items: tuple[...],
    steady_recall_items: tuple[RecallEvidence, ...],
    retrieval_requests: tuple[ContextRetrievalRequest, ...],
    evidence_index: Mapping[str, RecallEvidence],
    request_attachments: tuple[str, ...] = (),
    state_focus: StateFocusDecision | None = None,
) -> tuple[str, ...]:
    """Build the human-readable State snapshot content lines.

    IDs (work_item_ids, evidence_refs, profile refs) are NEVER rendered here:
    - profile slice shows selected profile fields and summary only
    - work slice shows title + status/priority only (via _work_item_line)
    - continuity slice shows kind + content (via _evidence_line)
    - evidence slice shows retrieved evidence content + reason (not id)

    Runtime bookkeeping (ids) travels separately on audit_refs / telemetry.
    """
    snapshot_work_items = _snapshot_work_items(work_items, state_focus=state_focus)
    lines: list[str] = []
    if state_focus is not None:
        lines.append(
            f"focus: family={state_focus.focus_family}; scope={state_focus.focus_scope}; budget={state_focus.context_budget}"
        )
    profile_lines = _profile_snapshot_summary_lines(profile_snapshot_refs)
    if profile_lines:
        lines.append("profile:")
        lines.extend(profile_lines)
    if snapshot_work_items:
        lines.append("work:")
        lines.extend(_work_item_line(work_item) for work_item in snapshot_work_items)
    if steady_recall_items:
        lines.append("path in view:")
        lines.extend(_evidence_line(evidence) for evidence in steady_recall_items)
    retrieval_lines = _retrieval_lines(retrieval_requests, evidence_index)
    if retrieval_lines:
        lines.append("evidence:")
        lines.extend(retrieval_lines)
    return tuple(lines)


def _build_retrieval_query(
    evidence: RecallEvidence,
    work_items: tuple[...],
    *,
    state_focus: StateFocusDecision | None = None,
) -> str:
    work_item_titles = " ".join(
        work_item.title for work_item in work_items if work_item.work_item_id in evidence.work_item_ids
    )
    focus_titles = ""
    state_focus_terms = ""
    if state_focus is not None:
        focus_ids = _state_focus_focus_work_item_ids(work_items, state_focus=state_focus)
        focus_titles = " ".join(work_item.title for work_item in work_items if work_item.work_item_id in focus_ids)
        state_focus_terms = " ".join(
            (
                state_focus.focus_family,
                state_focus.focus_scope,
                state_focus.context_budget,
            )
        )
    query = " ".join(
        part
        for part in (
            state_focus_terms,
            focus_titles,
            evidence.kind,
            evidence.content,
            work_item_titles,
        )
        if part
    )
    return query[:240]


def _build_retrieval_reason(
    evidence: RecallEvidence,
    work_items: tuple[...],
    reasons: tuple[str, ...] = (),
    *,
    state_focus: StateFocusDecision | None = None,
) -> str:
    # R1: emit work-item TITLES, not ids — the model cannot dereference ids.
    matched_titles = [
        work_item.title.strip() or "active work"
        for work_item in work_items
        if work_item.work_item_id in evidence.work_item_ids
    ]
    pieces: list[str] = []
    if state_focus is not None:
        focus_ids = set(_state_focus_focus_work_item_ids(work_items, state_focus=state_focus))
        focus_titles = [
            work_item.title.strip() or "active work"
            for work_item in work_items
            if work_item.work_item_id in focus_ids and work_item.work_item_id in evidence.work_item_ids
        ]
        if focus_titles:
            pieces.append(f"elephant focus kept {', '.join(focus_titles)} ahead of generic recall")
    if matched_titles:
        pieces.append(f"active elephant work-linked evidence for {', '.join(matched_titles)}")
    pieces.extend(reason for reason in reasons if reason not in pieces)
    if state_focus is not None:
        pieces.append(f"elephant focus scope={state_focus.focus_scope} budget={state_focus.context_budget}")
    if not pieces:
        if evidence.kind in {"summary", "decision", "lesson"}:
            pieces.append("high-value historical evidence")
        else:
            pieces.append("supporting continuity evidence")
    return "; ".join(pieces[:4])


def _estimate_tokens(content: str) -> int:
    return max(8, (len(content) // 4) + 1)


def _truncate_lines(content: tuple[str, ...], token_budget: int) -> tuple[str, ...]:
    remaining = max(token_budget, 0)
    lines: list[str] = []
    for line in content:
        if remaining <= 0:
            break
        lines.append(_truncate_text(line, limit=120))
        remaining -= _estimate_tokens(line)
    return tuple(lines) if lines else ("no content",)


def _truncate_text(value: str, *, limit: int) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    cut = text[:limit]
    boundary = max(
        cut.rfind(" "),
        cut.rfind(","),
        cut.rfind(";"),
        cut.rfind("|"),
    )
    if boundary < max(32, limit // 2):
        boundary = limit
    return f"{text[:boundary].rstrip(' ,;|')}..."


def _summary_content_for_layer(
    layer_name: str,
    session: Episode,
    work_items: tuple[...],
    recall_items: tuple[RecallEvidence, ...],
    recent_loop_context: tuple[str, ...],
    *,
    profile_snapshot_refs: tuple[str, ...] = (),
    steady_recall_items: tuple[RecallEvidence, ...],
    retrieval_requests: tuple[ContextRetrievalRequest, ...],
    replay_requests: tuple[ContextRetrievalRequest, ...] = (),
    request_attachments: tuple[str, ...] = (),
    state_focus: StateFocusDecision | None = None,
) -> tuple[str, ...]:
    """Build the compact SUMMARY content for a given layer (shown when the
    layer is displayed as a summary rather than raw content).

    Design rule (enforced by tests): never emit raw ids here. Runtime
    bookkeeping (evidence_ref, work_item_id, grounding_id, record_id, etc.)
    stays on audit_refs, not in model-visible prompt text.
    """
    if layer_name == "session_snapshot":
        snapshot_work_items = _snapshot_work_items(work_items, state_focus=state_focus)
        lines: list[str] = []
        if state_focus is not None:
            lines.append(
                f"elephant focus shape: family={state_focus.focus_family}; "
                f"scope={state_focus.focus_scope}; budget={state_focus.context_budget}"
            )
        # Profile facts already render in the frozen Personal Model block.
        # Repeating them here made the provider see duplicate profile facts.
        if state_focus is not None and state_focus.focus_scope == "personal_model" and not snapshot_work_items:
            lines.append("work slice suppressed by personal_model scope")
        if session.interruption_state:
            lines.append(f"interruption: {session.interruption_state}")
        if snapshot_work_items:
            lines.append(
                "active work: "
                + "; ".join(
                    f"{work_item.title} [{work_item.status}/{work_item.priority}]" for work_item in snapshot_work_items
                )
            )
        # Dedup by content hash across steady / retrieved snippets and against
        # the generation_context evidence projection. Same fact used to appear
        # under multiple headings simultaneously.
        seen_evidence_keys: set[str] = set()
        steady_lines: list[str] = []
        for evidence in steady_recall_items:
            key = _content_dedup_key(str(getattr(evidence, "content", "") or ""))
            if not key or key in seen_evidence_keys:
                continue
            seen_evidence_keys.add(key)
            steady_lines.append(_evidence_line(evidence))
        if steady_lines:
            lines.append("steady: " + " · ".join(steady_lines))
        retrieval_snippets: list[str] = []
        for request in retrieval_requests:
            for evidence_ref in request.evidence_refs:
                evidence = next((m for m in recall_items if m.evidence_id == evidence_ref), None)
                if evidence is None:
                    continue
                key = _content_dedup_key(str(getattr(evidence, "content", "") or ""))
                if not key or key in seen_evidence_keys:
                    continue
                evidence_line = _evidence_line(evidence)
                if _looks_like_profile_evidence_line(evidence_line):
                    continue
                seen_evidence_keys.add(key)
                retrieval_snippets.append(f"{evidence_line} (why: {request.reason})")
        if retrieval_snippets:
            lines.append("Pulled up just now: " + " · ".join(retrieval_snippets))
        # Intentionally do NOT echo request_attachments here — they
        # already render under their own turn-attachment layer.
        # Echoing them
        # inside session_snapshot was a duplicate that made the same
        # lines appear twice in the prompt.
        return tuple(lines)
    if layer_name == "replay_packet":
        lines = list(_replay_summary_lines(replay_requests, recall_items))
        return tuple(lines)
    if layer_name == "request_attachments":
        return request_attachments
    return recent_loop_context


def _profile_snapshot_summary_lines(
    profile_snapshot_refs: tuple[str, ...],
) -> tuple[str, ...]:
    """Render any legacy profile slice into human-readable lines.

    Clean Understanding prompts no longer populate this slice; active Personal
    Model claims are rendered by the stable prompt. This function remains a
    defensive filter for older cached context bundles and drops bookkeeping refs.
    """
    fields: list[str] = []
    summary_parts: list[str] = []
    other_lines: list[str] = []
    for ref in profile_snapshot_refs:
        cleaned = str(ref or "").strip()
        if not cleaned:
            continue
        # Drop the section heading itself.
        if cleaned.startswith("### "):
            continue
        if cleaned.startswith("- "):
            body = cleaned[2:].strip()
        elif cleaned.startswith("  - "):
            body = cleaned[4:].strip()
        else:
            other_lines.append(cleaned)
            continue
        if not body:
            continue
        if body.startswith("Pinned notes") or body.startswith("Continuity reminders"):
            other_lines.append(body)
            continue
        # Split "Preferred name: Bit" into a field label + value pair so
        # the downstream summary keeps the same shape it used to have.
        if ":" in body:
            label, value = body.split(":", 1)
            label_norm = label.strip().lower().replace(" ", "_")
            value_norm = value.strip()
            if label_norm and value_norm:
                fields.append(label_norm)
                summary_parts.append(f"{label.strip()}: {value_norm}")
                continue
        other_lines.append(body)
    lines: list[str] = []
    if fields:
        lines.append("known user fields: " + ", ".join(fields))
    if summary_parts:
        lines.append("user summary: " + " | ".join(summary_parts))
    lines.extend(other_lines)
    return tuple(lines)


def _retrieval_lines(
    retrieval_requests: tuple[ContextRetrievalRequest, ...],
    evidence_index: Mapping[str, RecallEvidence],
) -> tuple[str, ...]:
    lines: list[str] = []
    for request in retrieval_requests:
        for evidence_ref in request.evidence_refs:
            evidence = evidence_index.get(evidence_ref)
            if evidence is None:
                continue
            lines.append(f"{_evidence_line(evidence)} | why: {request.reason}")
    return tuple(lines)


@dataclass(frozen=True, slots=True)
class _ReplayRequestSpec:
    slot_name: str
    replay_mode: str
    max_compression: str
    desired_tokens: int
    minimum_tokens: int
    reason: str


_REPLAY_COMPRESSION_RANK = {
    "episode_summary": 0,
    "structured_summary": 1,
    "raw_turn": 2,
    "raw_trace": 3,
}


def _split_retrieval_requests(
    retrieval_requests: tuple[ContextRetrievalRequest, ...],
) -> tuple[tuple[ContextRetrievalRequest, ...], tuple[ContextRetrievalRequest, ...]]:
    snapshot_requests = tuple(request for request in retrieval_requests if request.layer_name != "replay_packet")
    replay_requests = tuple(request for request in retrieval_requests if request.layer_name == "replay_packet")
    return snapshot_requests, replay_requests


def _infer_replay_specs(
    recent_loop_context: tuple[str, ...],
    *,
    state_focus: StateFocusDecision | None = None,
) -> tuple[_ReplayRequestSpec, ...]:
    if not recent_loop_context:
        text = ""
        tokens: set[str] = set()
    else:
        text = " ".join(recent_loop_context).lower()
        tokens = _tokenize(text)
    explicit_replay = any(
        phrase in text
        for phrase in (
            "replay",
            "decision path",
            "reasoning chain",
            "action chain",
            "previous turn",
            "earlier turn",
            "earlier turns",
            "blocker history",
            "correction history",
            "rejected option",
        )
    )
    wants_reasoning = explicit_replay or (
        "why" in tokens and tokens.intersection({"did", "decision", "reasoning", "blocker", "because"})
    )
    wants_action = explicit_replay and tokens.intersection({"action", "step", "steps", "command", "tool", "run", "did"})
    wants_outcome = explicit_replay and tokens.intersection({"outcome", "result", "results"})
    replay_mode = (
        "episode"
        if explicit_replay and tokens.intersection({"previous", "earlier", "history", "across", "episode"})
        else "turn"
    )
    wants_raw_trace = "raw trace" in text or "exact trace" in text or ("raw" in tokens and "trace" in tokens)
    replay_specs: list[_ReplayRequestSpec] = []
    if wants_reasoning:
        replay_specs.append(
            _ReplayRequestSpec(
                slot_name="reasoning",
                replay_mode=replay_mode,
                max_compression="raw_trace" if wants_raw_trace else "structured_summary",
                desired_tokens=144 if wants_raw_trace else 72,
                minimum_tokens=32,
                reason="target the earlier reasoning path without defaulting raw trace into ordinary prompts",
            )
        )
    if wants_action:
        replay_specs.append(
            _ReplayRequestSpec(
                slot_name="action",
                replay_mode=replay_mode,
                max_compression="raw_turn",
                desired_tokens=96,
                minimum_tokens=32,
                reason="recover the concrete action chain for the active work item",
            )
        )
    if wants_outcome:
        replay_specs.append(
            _ReplayRequestSpec(
                slot_name="outcome",
                replay_mode=replay_mode,
                max_compression="episode_summary" if replay_mode == "episode" else "structured_summary",
                desired_tokens=64,
                minimum_tokens=24,
                reason="surface the outcome chain that closes the earlier decision path",
            )
        )
    if replay_specs:
        return tuple(replay_specs)
    if state_focus is not None and (state_focus.focus_family == "resume" or state_focus.continuity_signal != "none"):
        if state_focus.focus_scope in {"episode", "lineage"}:
            # R1: replay reason is human-readable; work_item_ids do not render.
            return (
                _ReplayRequestSpec(
                    slot_name="reasoning",
                    replay_mode="episode" if state_focus.focus_scope == "lineage" else "turn",
                    max_compression="structured_summary",
                    desired_tokens=64 if state_focus.context_budget == "narrow" else 96,
                    minimum_tokens=24,
                    reason="resume elephant focus requested bounded continuity replay",
                ),
            )
    return ()


def _schedule_replay_requests(
    *,
    session: Episode,
    work_items: tuple[...],
    recall_items: tuple[RecallEvidence, ...],
    recent_loop_context: tuple[str, ...],
    token_budget: int,
    state_focus: StateFocusDecision | None = None,
) -> tuple[ContextRetrievalRequest, ...]:
    replay_specs = _infer_replay_specs(recent_loop_context, state_focus=state_focus)
    if not replay_specs or token_budget <= 0:
        return ()
    remaining = token_budget
    requests: list[ContextRetrievalRequest] = []
    for index, replay_intent in enumerate(replay_specs):
        candidate = _select_replay_evidence(
            session=session,
            work_items=work_items,
            recall_items=recall_items,
            recent_loop_context=recent_loop_context,
            slot_name=replay_intent.slot_name,
            replay_mode=replay_intent.replay_mode,
            max_compression=replay_intent.max_compression,
            state_focus=state_focus,
        )
        if candidate is None:
            continue
        selected_tokens = min(replay_intent.desired_tokens, remaining)
        if selected_tokens <= 0:
            break
        remaining -= selected_tokens
        evidence, detail_reason = candidate
        requests.append(
            ContextRetrievalRequest(
                request_id=f"{session.episode_id}:replay:{index}",
                layer_name="replay_packet",
                session_id=session.episode_id,
                query=" ".join(recent_loop_context)[:240],
                evidence_refs=(evidence.evidence_id,),
                work_item_ids=tuple(
                    work_item.work_item_id
                    for work_item in work_items
                    if work_item.work_item_id in evidence.work_item_ids
                ),
                token_budget=selected_tokens,
                priority=max(0, 120 - index * 10),
                reason=f"{replay_intent.reason}; {detail_reason}",
                target_slots=(replay_intent.slot_name,),
                max_compression=replay_intent.max_compression,
                replay_mode=replay_intent.replay_mode,
            )
        )
    return tuple(requests)


def _select_replay_evidence(
    *,
    session: Episode,
    work_items: tuple[...],
    recall_items: tuple[RecallEvidence, ...],
    recent_loop_context: tuple[str, ...],
    slot_name: str,
    replay_mode: str,
    max_compression: str,
    state_focus: StateFocusDecision | None = None,
) -> tuple[RecallEvidence, str] | None:
    del (
        session,
        work_items,
        recall_items,
        recent_loop_context,
        slot_name,
        replay_mode,
        max_compression,
        state_focus,
    )
    return None


def _replay_rank(compression: str) -> int:
    return _REPLAY_COMPRESSION_RANK.get(compression.strip().lower(), _REPLAY_COMPRESSION_RANK["structured_summary"])


def _project_replay_slot(slot: StructuredTurnSlot, *, max_compression: str) -> tuple[StructuredTurnSlot, bool]:
    if _replay_rank(slot.compression) <= _replay_rank(max_compression):
        return slot, False
    return (
        StructuredTurnSlot(
            summary=slot.summary,
            detail=(),
            compression=max_compression,
            provenance=slot.provenance,
            source_refs=slot.source_refs,
            linkage_refs=slot.linkage_refs,
        ),
        True,
    )


def _replay_lines(
    replay_requests: tuple[ContextRetrievalRequest, ...],
    evidence_index: Mapping[str, RecallEvidence],
) -> tuple[str, ...]:
    """Render replay slots as human-readable content.

    Drops evidence_refs and artifact_ids from the output. The replay mode,
    slot name, and projected summary/detail are enough for the model to use
    the replay content; ids are runtime bookkeeping only.
    """
    del replay_requests, evidence_index
    return ()


def _replay_summary_lines(
    replay_requests: tuple[ContextRetrievalRequest, ...],
    recall_items: tuple[RecallEvidence, ...],
) -> tuple[str, ...]:
    """Compact replay summary lines for the prompt. IDs are omitted."""
    lines: list[str] = []
    for request in replay_requests:
        slot_summary = ", ".join(request.target_slots) or "reasoning"
        lines.append(
            f"replay slots={slot_summary}; mode={request.replay_mode}; max_compression={request.max_compression}"
        )
    return tuple(lines)


def _replay_packet_trace_reason(
    replay_requests: tuple[ContextRetrievalRequest, ...],
) -> str:
    parts = []
    for request in replay_requests:
        slot_summary = ", ".join(request.target_slots) or "reasoning"
        parts.append(f"{slot_summary} via {request.replay_mode}/{request.max_compression}")
    return (
        f"targeted replay kept {len(replay_requests)} slice(s) with explicit slot budgets: {'; '.join(parts)}; "
        "stable policy stayed in EpisodeFrozenContext while replay detail remained request-time only"
    )


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-z0-9_]+", text.lower()) if token}


def _thematic_tokens(
    session: Episode,
    work_items: tuple[...],
    recent_loop_context: tuple[str, ...],
) -> set[str]:
    tokens: set[str] = set()
    for work_item in work_items:
        tokens.update(_tokenize(work_item.work_item_id))
        tokens.update(_tokenize(work_item.title))
        tokens.update(_tokenize(work_item.status))
        tokens.update(_tokenize(work_item.priority))
        tokens.update(_tokenize(" ".join(work_item.dependencies)))
        tokens.update(_tokenize(" ".join(work_item.evidence_refs)))
    tokens.update(_tokenize(" ".join(recent_loop_context)))
    tokens.update(_continuity_marker_tokens(session))
    return tokens


def _continuity_marker_tokens(session: Episode) -> set[str]:
    if not session.interruption_state:
        return set()
    return _tokenize(session.interruption_state) | {
        "resume",
        "recovery",
        "continuity",
        "interruption",
        "gap",
    }


def _context_evidence_score(
    evidence: RecallEvidence,
    *,
    session: Episode,
    work_items: tuple[...],
    state_focus: StateFocusDecision | None = None,
    layer_name: str,
    recent_loop_context: tuple[str, ...] = (),
    return_reasons: bool = False,
) -> float | tuple[float, tuple[str, ...]]:
    work_item_ids = {work_item.work_item_id for work_item in work_items}
    work_titles_by_id = {work_item.work_item_id: (work_item.title.strip() or "active work") for work_item in work_items}
    thematic_tokens = _thematic_tokens(session, work_items, recent_loop_context)
    continuity_markers = _continuity_marker_tokens(session)
    reasons: list[str] = []
    score = 0.0
    if evidence.episode_id == session.episode_id:
        score += 4.0
        reasons.append("current-session evidence")
    overlap = work_item_ids.intersection(evidence.work_item_ids)
    score += float(len(overlap)) * 5.0
    if overlap:
        # R1: reason strings must cite human-readable titles, not work ids.
        reasons.append(
            f"active elephant work-linked: {', '.join(sorted(work_titles_by_id.get(wid, 'active work') for wid in overlap))}"
        )
    focus_overlap = set(_state_focus_focus_work_item_ids(work_items, state_focus=state_focus)).intersection(
        evidence.work_item_ids
    )
    score += float(len(focus_overlap)) * 6.0
    if focus_overlap:
        reasons.append(
            f"elephant focus: {', '.join(sorted(work_titles_by_id.get(wid, 'active work') for wid in focus_overlap))}"
        )
    kind_bonus = {
        "summary": 3.0,
        "decision": 3.5,
        "lesson": 3.0,
        "semantic": 2.5,
        "procedural": 2.5,
        "artifact": 1.0,
    }
    score += kind_bonus.get(evidence.kind, 0.0)
    if evidence.kind in {"summary", "decision", "lesson"}:
        reasons.append(f"high-value kind: {evidence.kind}")
    elif evidence.kind in {"semantic", "procedural"}:
        reasons.append(f"durable kind: {evidence.kind}")
    elif evidence.kind == "artifact":
        reasons.append("artifact support")
    tags = set(evidence.tags)
    if "corrected" in tags:
        score += 2.0
        reasons.append("corrected evidence")
    if "consolidated" in tags:
        score += 1.0
        reasons.append("consolidated evidence")
    if "filler" in tags:
        score -= 4.0
    if "continuity" in tags or "recovery" in tags:
        score += 1.0
    if state_focus is not None:
        if state_focus.focus_scope == "personal_model" and evidence.kind in {
            "summary",
            "decision",
            "semantic",
        }:
            score += 1.5
            reasons.append("personal-model recall")
        if state_focus.focus_scope == "state" and evidence.kind in {
            "artifact",
            "procedural",
        }:
            score += 1.0
            reasons.append("elephant-scoped recall")
        if state_focus.continuity_signal != "none" and evidence.kind in {
            "summary",
            "decision",
            "semantic",
            "procedural",
        }:
            score += 1.0
            reasons.append("elephant focus resume recovery")
        if (
            state_focus.context_budget == "narrow"
            and state_focus.focus_work_item_ids
            and not focus_overlap
            and not overlap
        ):
            score -= 1.5
    text_tokens = _tokenize(evidence.content) | _tokenize(" ".join(evidence.tags))
    thematic_overlap = tuple(sorted(text_tokens & thematic_tokens))
    if thematic_overlap:
        score += float(len(thematic_overlap)) * 1.75
        reasons.append(f"theme overlap: {', '.join(thematic_overlap[:4])}")
    if continuity_markers and (
        continuity_markers.intersection(text_tokens)
        or overlap
        or evidence.kind in {"summary", "decision", "lesson", "semantic", "procedural"}
    ):
        score += 2.0
        reasons.append("continuity recovery support")
    if layer_name == "steady" and session.interruption_state:
        score += 1.5
    if evidence.created_at is not None:
        score += evidence.created_at.timestamp() / 10_000_000
    score += min(len(evidence.tags), 4) * 0.001
    reason_tuple = tuple(dict.fromkeys(reasons))
    if return_reasons:
        return score, reason_tuple
    return score


def _retrieval_priority_bucket(
    evidence: RecallEvidence,
    *,
    session: Episode,
    work_items: tuple[...],
    recent_loop_context: tuple[str, ...],
    state_focus: StateFocusDecision | None = None,
) -> int:
    work_item_ids = {work_item.work_item_id for work_item in work_items}
    text_tokens = _tokenize(evidence.content) | _tokenize(" ".join(evidence.tags))
    if set(_state_focus_focus_work_item_ids(work_items, state_focus=state_focus)).intersection(evidence.work_item_ids):
        return 4
    if work_item_ids.intersection(evidence.work_item_ids):
        return 3
    if _thematic_tokens(session, work_items, recent_loop_context).intersection(text_tokens):
        return 2
    if evidence.episode_id == session.episode_id and evidence.kind in {
        "summary",
        "decision",
        "lesson",
        "semantic",
        "procedural",
    }:
        return 1
    return 0


def _plan_rationale(
    session: Episode,
    work_items: tuple[...],
    recall_items: tuple[RecallEvidence, ...],
    budgets: ContextBudgetPlan,
    retrieval_requests: tuple[ContextRetrievalRequest, ...],
    *,
    state_focus: StateFocusDecision | None = None,
) -> str:
    _, replay_requests = _split_retrieval_requests(retrieval_requests)
    if replay_requests:
        if state_focus is not None:
            return (
                f"elephant focus {state_focus.focus_family} with scope={state_focus.focus_scope} requested bounded replay, "
                "so the frame pulls targeted reasoning/action evidence without moving stable policy out of EpisodeFrozenContext"
            )
        return (
            "the current request explicitly asks for earlier decision context, so a bounded replay layer "
            "pulls targeted reasoning/action evidence without moving stable policy out of EpisodeFrozenContext"
        )
    if state_focus is not None and state_focus.focus_scope == "personal_model":
        return "personal-model elephant focus suppresses unrelated work refs so the session snapshot stays centered on durable Personal Model continuity"
    if state_focus is not None and state_focus.context_budget == "narrow" and state_focus.focus_work_item_ids:
        # R1: rationale stays human-readable — the model cannot dereference work_item_ids.
        return "elephant focus narrows the session snapshot and compacts retrieval around the active continuity slice"
    if session.interruption_state:
        return (
            f"continuity recovery is prioritized because the session resumed from {session.interruption_state}; "
            "steady history is compacted and durable retrieval is reintroduced"
        )
    if len(recall_items) > 5 and budgets.overflow_tokens > 0:
        return (
            "long-running session overflow pushes the planner to summarize steady history "
            "and schedule active elephant work-linked retrieval"
        )
    if work_items:
        return f"active elephant work item {work_items[0].work_item_id} is kept close to the reasoning loop"
    return "stable prompt assembly with explicit budget allocation"
