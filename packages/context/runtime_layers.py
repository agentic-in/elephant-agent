"""Context runtime planning protocols and deterministic implementations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from packages.contracts import Episode
from packages.contracts.runtime import (
    StateFocusDecision,
    RecallEvidence,
    PromptEnvelope,
)


from .runtime_types import (
    ContextAssemblyPlan,
    ContextBudgetPlan,
    ContextBudgetRequest,
    ContextLayerBudget,
    ContextRetrievalRequest,
    ContextSourceTrace,
    ContextSummaryRequest,
    EpisodeReplay,
    EpisodeFrame,
    StateSnapshot,
    EpisodeFrozenContext,
    LoopContext,
    RequestAttachments,
)
from .runtime_support import (
    _budget_for,
    _build_retrieval_query,
    _build_retrieval_reason,
    _context_evidence_score,
    _derived_source_refs,
    _estimate_tokens,
    _replay_lines,
    _retrieval_priority_bucket,
    _schedule_replay_requests,
    _select_steady_recall_items,
    _snapshot_work_items,
    _session_snapshot_lines,
    _split_retrieval_requests,
    _summary_content_for_layer,
    _truncate_lines,
)


def _operational_layer_heading(layer_name: str) -> str:
    """Human-readable heading for each context frame layer.

    The model used to see raw PascalCase class names
    (``EpisodeFrozenContext``, ``StateSnapshot``, ``LoopContext``,
    ``RequestAttachments``, ``EpisodeReplay``) as section titles. That
    framework-speak leaked the class graph into the prompt without
    teaching the model anything about what each section was *for*.
    These labels replace the class names with short natural phrases
    that describe the content.
    """
    labels = {
        "stable_prefix": "Session brief",
        "session_snapshot": "Session snapshot",
        "replay_packet": "Recent turns",
        "loop_context": "Recent turn context",
        "request_attachments": "Turn attachments",
    }
    return labels.get(layer_name, layer_name.replace("_", " ").title())


def _render_live_prompt_section(
    heading: str,
    *,
    content: tuple[str, ...],
    summary: str | None = None,
    token_budget: int | None = None,
    summary_replaces_content: bool = False,
    raw_content: bool = False,
    suppress_heading: bool = False,
) -> str:
    normalized_summary = str(summary or "").strip()
    if normalized_summary.casefold() == "no content" and not tuple(
        str(line).strip() for line in content if str(line).strip()
    ):
        normalized_summary = ""
    if normalized_summary and summary_replaces_content:
        lines: list[str] = []
    else:
        lines = [str(line).strip() for line in content if str(line).strip()]
        if token_budget is not None:
            lines = list(_truncate_lines(tuple(lines), token_budget))
    if not lines and not normalized_summary:
        return ""
    rendered: list[str] = []
    if not suppress_heading:
        rendered.append(f"## {heading}")
    if normalized_summary:
        rendered.append(normalized_summary)
    if raw_content:
        rendered.extend(lines)
    else:
        rendered.extend(f"- {line}" for line in lines)
    return "\n".join(rendered).strip()


def build_prompt_envelope(frame: EpisodeFrame | None) -> PromptEnvelope:
    """Build live provider prompt sections from an Episode frame."""

    if frame is None:
        return PromptEnvelope()
    # The stable prefix already contains fully-formed `### Who you are`,
    # `### Your own voice`, etc. Wrapping it under another `## Session
    # brief` heading was pure nesting overhead that the model (and
    # Dashboard) simply printed as a lone literal line. Suppress it.
    frozen_prefix = _render_live_prompt_section(
        "Session brief",
        content=frame.stable_prefix.content,
        raw_content=True,
        suppress_heading=True,
    )
    session_parts: list[str] = []
    loop_parts = []
    if frame.loop_context is not None:
        loop_parts.append(
            _render_live_prompt_section(
                "Recent turn context",
                content=frame.loop_context.content,
                token_budget=frame.loop_context.token_budget,
            )
        )
    if frame.request_attachments is not None:
        loop_parts.append(
            _render_live_prompt_section(
                "Turn attachments",
                content=frame.request_attachments.content,
                token_budget=frame.request_attachments.token_budget,
            )
        )
    return PromptEnvelope(
        frozen_prefix=frozen_prefix,
        session_snapshot="\n\n".join(part for part in session_parts if part.strip()),
        loop_context="\n\n".join(part for part in loop_parts if part.strip()),
    )


@runtime_checkable
class SummaryHook(Protocol):
    def summarize(
        self,
        *,
        session: Episode,
        layer_name: str,
        content: tuple[str, ...],
        token_budget: int,
        reason: str,
    ) -> str:
        """Summarize content for a single context layer."""


@runtime_checkable
class RetrievalScheduler(Protocol):
    def schedule(
        self,
        *,
        session: Episode,
        work_items: tuple[...],
        recall_items: tuple[RecallEvidence, ...],
        recent_loop_context: tuple[str, ...] = (),
        token_budget: int,
        budget_plan: ContextBudgetPlan,
        state_focus: StateFocusDecision | None = None,
    ) -> tuple[ContextRetrievalRequest, ...]:
        """Schedule retrieval requests for the current session."""


@runtime_checkable
class BudgetManager(Protocol):
    def allocate(self, total_tokens: int, requests: tuple[ContextBudgetRequest, ...]) -> ContextBudgetPlan:
        """Allocate explicit token budgets to ordered layers."""


@runtime_checkable
class PromptRenderer(Protocol):
    def render(self, plan: ContextAssemblyPlan) -> str:
        """Render a structured prompt bundle."""


@runtime_checkable
class ContextPlanner(Protocol):
    def plan(
        self,
        *,
        session: Episode,
        work_items: tuple[...],
        recall_items: tuple[RecallEvidence, ...],
        total_tokens: int,
        instruction_refs: tuple[str, ...],
        recent_loop_context: tuple[str, ...],
        state_focus: StateFocusDecision | None = None,
        profile_snapshot_refs: tuple[str, ...] = (),
        artifacts: tuple[str, ...] = (),
    ) -> ContextAssemblyPlan:
        """Plan layered context from structured runtime state."""


class DeterministicBudgetManager:
    """Allocate context budgets in explicit priority order."""

    def allocate(self, total_tokens: int, requests: tuple[ContextBudgetRequest, ...]) -> ContextBudgetPlan:
        ordered = sorted(
            enumerate(requests),
            key=lambda item: (
                1 if item[1].required else 0,
                item[1].priority,
                -item[0],
            ),
            reverse=True,
        )
        remaining = max(total_tokens, 0)
        allocations: list[ContextLayerBudget] = []
        omitted: list[str] = []
        for _, request in ordered:
            requested = max(request.desired_tokens, request.minimum_tokens)
            if remaining <= 0:
                allocations.append(
                    ContextLayerBudget(
                        layer_name=request.layer_name,
                        requested_tokens=requested,
                        allocated_tokens=0,
                        required=request.required,
                        priority=request.priority,
                        omitted=True,
                        source_refs=request.source_refs,
                    )
                )
                omitted.append(request.layer_name)
                continue
            allocated = min(requested, remaining)
            if request.required and allocated < request.minimum_tokens:
                omitted.append(request.layer_name)
            elif not request.required and allocated < requested:
                omitted.append(request.layer_name)
            allocations.append(
                ContextLayerBudget(
                    layer_name=request.layer_name,
                    requested_tokens=requested,
                    allocated_tokens=allocated,
                    required=request.required,
                    priority=request.priority,
                    omitted=allocated == 0,
                    source_refs=request.source_refs,
                )
            )
            remaining -= allocated
        overflow = max(sum(request.desired_tokens for request in requests) - total_tokens, 0)
        return ContextBudgetPlan(
            total_tokens=total_tokens,
            allocations=tuple(allocations),
            overflow_tokens=overflow,
            omitted_layers=tuple(dict.fromkeys(omitted)),
        )


class DeterministicRetrievalScheduler:
    """Score recall_items deterministically against session work_items."""

    def schedule(
        self,
        *,
        session: Episode,
        work_items: tuple[...],
        recall_items: tuple[RecallEvidence, ...],
        recent_loop_context: tuple[str, ...] = (),
        token_budget: int,
        budget_plan: ContextBudgetPlan,
        state_focus: StateFocusDecision | None = None,
    ) -> tuple[ContextRetrievalRequest, ...]:
        scored: list[tuple[int, float, float, RecallEvidence, tuple[str, ...]]] = []
        for evidence in recall_items:
            score, reasons = _context_evidence_score(
                evidence,
                session=session,
                work_items=work_items,
                state_focus=state_focus,
                layer_name="retrieval",
                recent_loop_context=recent_loop_context,
                return_reasons=True,
            )
            bucket = _retrieval_priority_bucket(
                evidence,
                session=session,
                work_items=work_items,
                recent_loop_context=recent_loop_context,
                state_focus=state_focus,
            )
            recency = evidence.created_at.timestamp() if evidence.created_at is not None else 0.0
            scored.append((bucket, score, recency, evidence, reasons))

        scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3].evidence_id))
        remaining = max(token_budget, 0)
        requests: list[ContextRetrievalRequest] = []
        for index, (_, _, _, evidence, reasons) in enumerate(scored):
            estimated_tokens = _estimate_tokens(evidence.content)
            if remaining <= 0:
                break
            selected_tokens = min(estimated_tokens, remaining)
            if selected_tokens <= 0:
                continue
            remaining -= selected_tokens
            requests.append(
                ContextRetrievalRequest(
                    request_id=f"{session.episode_id}:retrieval:{index}",
                    layer_name="session_snapshot",
                    session_id=session.episode_id,
                    query=_build_retrieval_query(evidence, work_items, state_focus=state_focus),
                    evidence_refs=(evidence.evidence_id,),
                    work_item_ids=evidence.work_item_ids,
                    token_budget=selected_tokens,
                    priority=max(0, 100 - index * 10),
                    reason=_build_retrieval_reason(evidence, work_items, reasons, state_focus=state_focus),
                )
            )

        replay_budget = _budget_for(budget_plan, "replay_packet")
        if replay_budget <= 0:
            return tuple(requests)
        return tuple(requests) + _schedule_replay_requests(
            session=session,
            work_items=work_items,
            recall_items=recall_items,
            recent_loop_context=recent_loop_context,
            token_budget=replay_budget,
            state_focus=state_focus,
        )


class DeterministicSummaryHook:
    """Summarize a layer by compressing content into inspectable bullets."""

    def summarize(
        self,
        *,
        session: Episode,
        layer_name: str,
        content: tuple[str, ...],
        token_budget: int,
        reason: str,
    ) -> str:
        # The `heading summary\nreason: ...` wrapper was debug telemetry
        # masquerading as model-facing text. The model doesn't need to
        # know *why* the runtime compressed this layer; it just needs
        # the content. We keep a single invisible comment line (Telemetry
        # only; hidden from the model via the HTML-comment strip path)
        # for call-site audit and render only the bullets otherwise.
        del reason, layer_name  # telemetry-only inputs, see docstring
        body = tuple(
            line for line in _truncate_lines(content, token_budget) if str(line).strip().casefold() != "no content"
        )
        pieces: list[str] = []
        pieces.extend(f"- {line}" for line in body)
        if session.interruption_state:
            pieces.append(f"- continuity: {session.interruption_state}")
        return "\n".join(pieces)


class MarkdownPromptRenderer:
    """Render the assembled plan as stable markdown-like text.

    This renderer MUST NOT emit any runtime-owned identifier (record id,
    evidence id, grounding id, loop id, step id, work item id, session id
    other than the episode label header). Such identifiers have no
    corresponding tool by which the model can dereference them, so they
    would only pollute the prompt and prefix cache. Identifiers stay on
    ``ContextLayerSnapshot.source_refs`` for audit/telemetry only.
    """

    def render(self, plan: ContextAssemblyPlan) -> str:
        """Render the assembled plan.

        We deliberately drop the old `# Conversation context` + `-
        rationale: ...` header pair — that rationale is telemetry
        about *why* the runtime chose this budget allocation, which
        has no behavioural signal for the model. We also suppress the
        wrapper heading for the stable-prefix layer because its
        content already carries its own `### ...` subheadings.
        """
        lines: list[str] = []
        for layer in plan.layers:
            if layer.layer_name == "session_snapshot":
                continue
            content_lines = tuple(line for line in layer.content if str(line).strip())
            summary = str(layer.summary or "").strip()
            if summary.casefold() == "no content":
                summary = ""
            if layer.layer_name != "stable_prefix" and not content_lines and not summary:
                continue
            suppress_heading = layer.layer_name == "stable_prefix"
            if not suppress_heading:
                lines.append(f"## {_operational_layer_heading(layer.layer_name)}")
            if summary:
                lines.append(summary)
            for line in content_lines:
                lines.append(f"- {line}")
            lines.append("")
        return "\n".join(lines).strip()


class EpisodeFrameBuilder:
    """Build the explicit Episode frame from selected runtime slices."""

    def build(
        self,
        *,
        session: Episode,
        instruction_refs: tuple[str, ...],
        profile_snapshot_refs: tuple[str, ...],
        work_items: tuple[...],
        recall_items: tuple[RecallEvidence, ...],
        recent_loop_context: tuple[str, ...],
        request_attachments: tuple[str, ...],
        budgets: ContextBudgetPlan,
        summary_requests: tuple[ContextSummaryRequest, ...],
        retrieval_requests: tuple[ContextRetrievalRequest, ...],
        rationale: str,
        source_trace: tuple[ContextSourceTrace, ...],
        state_focus: StateFocusDecision | None = None,
    ) -> EpisodeFrame:
        snapshot_work_items = _snapshot_work_items(work_items, state_focus=state_focus)
        steady_recall_items = _select_steady_recall_items(
            recall_items,
            session=session,
            work_items=work_items,
            state_focus=state_focus,
        )
        evidence_index = {evidence.evidence_id: evidence for evidence in recall_items}
        summary_by_layer = {request.layer_name: request for request in summary_requests}
        snapshot_retrieval_requests, replay_retrieval_requests = _split_retrieval_requests(retrieval_requests)
        snapshot_summary = None
        snapshot_request = summary_by_layer.get("session_snapshot")
        if snapshot_request is not None:
            snapshot_summary = DeterministicSummaryHook().summarize(
                session=session,
                layer_name="session_snapshot",
                content=_summary_content_for_layer(
                    "session_snapshot",
                    session,
                    work_items,
                    recall_items,
                    recent_loop_context,
                    profile_snapshot_refs=profile_snapshot_refs,
                    steady_recall_items=steady_recall_items,
                    retrieval_requests=snapshot_retrieval_requests,
                    replay_requests=replay_retrieval_requests,
                    request_attachments=request_attachments,
                    state_focus=state_focus,
                ),
                token_budget=snapshot_request.token_budget,
                reason=snapshot_request.reason,
            )
        retrieved_evidence_refs = tuple(
            dict.fromkeys(
                evidence_ref for request in snapshot_retrieval_requests for evidence_ref in request.evidence_refs
            )
        )
        replay_summary = None
        replay_request = summary_by_layer.get("replay_packet")
        if replay_request is not None and replay_retrieval_requests:
            replay_summary = DeterministicSummaryHook().summarize(
                session=session,
                layer_name="replay_packet",
                content=_summary_content_for_layer(
                    "replay_packet",
                    session,
                    work_items,
                    recall_items,
                    recent_loop_context,
                    profile_snapshot_refs=profile_snapshot_refs,
                    steady_recall_items=steady_recall_items,
                    retrieval_requests=snapshot_retrieval_requests,
                    replay_requests=replay_retrieval_requests,
                    request_attachments=request_attachments,
                    state_focus=state_focus,
                ),
                token_budget=replay_request.token_budget,
                reason=replay_request.reason,
            )
        replay_evidence_refs = tuple(
            dict.fromkeys(
                evidence_ref for request in replay_retrieval_requests for evidence_ref in request.evidence_refs
            )
        )
        replay_packet = None
        if replay_retrieval_requests:
            replay_packet = EpisodeReplay(
                source_refs=replay_evidence_refs,
                evidence_refs=replay_evidence_refs,
                content=_replay_lines(replay_retrieval_requests, evidence_index),
                token_budget=_budget_for(budgets, "replay_packet"),
                summary=replay_summary,
            )
        session_snapshot = StateSnapshot(
            source_refs=tuple(
                dict.fromkeys(
                    (
                        *profile_snapshot_refs,
                        *(work_item.work_item_id for work_item in snapshot_work_items),
                        *(evidence.evidence_id for evidence in steady_recall_items),
                        *retrieved_evidence_refs,
                    )
                )
            ),
            profile_refs=profile_snapshot_refs or (f"profile:{session.personal_model_id}:user-snapshot",),
            work_refs=tuple(work_item.work_item_id for work_item in snapshot_work_items),
            evidence_refs=retrieved_evidence_refs,
            content=_session_snapshot_lines(
                session=session,
                profile_snapshot_refs=profile_snapshot_refs,
                work_items=work_items,
                steady_recall_items=steady_recall_items,
                retrieval_requests=snapshot_retrieval_requests,
                evidence_index=evidence_index,
                request_attachments=request_attachments,
                state_focus=state_focus,
            ),
            token_budget=_budget_for(budgets, "session_snapshot"),
            summary=snapshot_summary,
        )
        return EpisodeFrame(
            session_id=session.episode_id,
            profile_id=session.personal_model_id,
            stable_prefix=EpisodeFrozenContext(
                source_refs=instruction_refs,
                content=instruction_refs,
                token_budget=_budget_for(budgets, "stable_prefix"),
            ),
            session_snapshot=session_snapshot,
            replay_packet=replay_packet,
            loop_context=(
                LoopContext(
                    source_refs=tuple(f"loop:{index}" for index, _ in enumerate(recent_loop_context, start=1)),
                    content=recent_loop_context,
                    token_budget=_budget_for(budgets, "loop_context"),
                )
                if recent_loop_context
                else None
            ),
            request_attachments=(
                RequestAttachments(
                    source_refs=_derived_source_refs("attachment", request_attachments),
                    content=request_attachments,
                    token_budget=_budget_for(budgets, "request_attachments"),
                )
                if request_attachments
                else None
            ),
            rationale=rationale,
            source_trace=source_trace,
        )
