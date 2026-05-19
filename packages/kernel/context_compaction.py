"""Kernel helpers for prompt-projection compaction retries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from packages.context import estimate_projection_tokens
from packages.contracts.runtime import ContextBundle


@dataclass(frozen=True, slots=True)
class EpisodeContinuityPacket:
    packet_id: str
    text: str
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextCompactionOutcome:
    context: ContextBundle
    result: object
    packet: EpisodeContinuityPacket


def looks_like_context_overflow(error: BaseException) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "context length",
            "context_length",
            "maximum context",
            "prompt is too long",
            "prompt too long",
            "too many tokens",
            "request payload too large",
            "payload too large",
            "413",
        )
    )


def projection_compaction_detail(result: object) -> str:
    before_tokens = getattr(result, "before_tokens", 0)
    after_tokens = getattr(result, "after_tokens", 0)
    before_messages = getattr(result, "before_line_count", 0)
    after_messages = getattr(result, "after_line_count", 0)
    compacted_messages = getattr(result, "compacted_line_count", 0)
    reason = str(getattr(result, "reason", "") or "preflight")
    head_count = getattr(result, "protected_head_count", 0)
    tail_count = getattr(result, "protected_tail_count", 0)
    protected_ranges = tuple(getattr(result, "protected_ranges", ()) or ())
    selected_raw_ids = tuple(getattr(result, "selected_raw_ids", ()) or ())
    summary_hash = str(getattr(result, "summary_hash", "") or "").strip() or "<none>"
    semantic_selected = getattr(result, "semantic_anchor_selected_count", 0)
    semantic_cached = getattr(result, "semantic_anchor_cached_count", 0)
    semantic_pending = getattr(result, "semantic_anchor_pending_count", 0)
    semantic_missed = getattr(result, "missed_projection_embedding_count", 0)
    semantic_wait_ms = getattr(result, "semantic_anchor_wait_ms", 0)
    return (
        f"reason={reason} tokens={before_tokens}->{after_tokens} "
        f"messages={before_messages}->{after_messages} compacted_messages={compacted_messages} "
        f"head={head_count} tail={tail_count} protected_ranges={_csv(protected_ranges, separator='|')} "
        f"selected_raw={len(selected_raw_ids)} summary_hash={summary_hash} "
        f"semantic_selected={semantic_selected} semantic_cached={semantic_cached} "
        f"semantic_pending={semantic_pending} semantic_missed={semantic_missed} "
        f"semantic_wait_ms={semantic_wait_ms}"
    )


def latest_compacted_projection(context_capability: object) -> object | None:
    result = getattr(context_capability, "last_projection_compaction", None)
    if result is None or not bool(getattr(result, "compacted", False)):
        return None
    return result


def flush_projection_cache(context_capability: object) -> None:
    flush = getattr(context_capability, "flush_projection_cache", None)
    if callable(flush):
        flush()


def stage_context_usage(
    stage: Any,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> None:
    if not callable(stage) or max(prompt_tokens, completion_tokens, total_tokens) <= 0:
        return
    stage(
        "context-usage",
        f"prompt_tokens={prompt_tokens} completion_tokens={completion_tokens} total_tokens={total_tokens}",
    )


def estimate_context_projection_tokens(context: Any) -> int:
    rendered_prompt = str(getattr(context, "rendered_prompt", "") or "").strip()
    if rendered_prompt:
        return estimate_projection_tokens(rendered_prompt)
    envelope = getattr(context, "prompt_envelope", None)
    combined_prompt = getattr(envelope, "combined_prompt", None)
    if callable(combined_prompt):
        return estimate_projection_tokens(combined_prompt())
    return 0


def stage_context_projection(stage: Any, context: Any, *, source: str = "generation") -> None:
    if not callable(stage):
        return
    prompt_tokens = estimate_context_projection_tokens(context)
    token_budget = int(getattr(context, "token_budget", 0) or 0)
    if prompt_tokens <= 0 and token_budget <= 0:
        return
    stage(
        "context-projection",
        f"prompt_tokens={prompt_tokens} token_budget={token_budget} source={source}",
    )


def compact_context_after_usage(
    *,
    dependencies: Any,
    execution: Any,
    context: Any,
    stage: Any,
    usage_ratio: float = 0.85,
) -> object | None:
    """Legacy kernel-layer compaction — now a no-op.

    Context compression is handled by the CLI layer via synchronous reflect
    compress after each turn. This stub is kept for API compatibility.
    """
    return None


def episode_continuity_packet(
    *,
    request: Any,
    result: Any,
    source_step_ids: tuple[str, ...],
) -> EpisodeContinuityPacket:
    packet_id = f"episode-continuity:{getattr(request, 'loop_id', '') or getattr(request, 'request_id', 'unknown')}"
    source_refs = tuple(
        ref
        for ref in (
            getattr(request, "source_id", ""),
            getattr(request, "episode_id", ""),
            getattr(request, "loop_id", ""),
            *source_step_ids,
        )
        if str(ref or "").strip()
    )
    summary = str(getattr(result, "summary", "") or "").strip() or projection_compaction_detail(result)
    protected_ranges = tuple(getattr(result, "protected_ranges", ()) or ())
    selected_raw_ids = tuple(getattr(result, "selected_raw_ids", ()) or ())
    summary_hash = str(getattr(result, "summary_hash", "") or "").strip() or "<none>"
    lines = (
        "## EpisodeContinuityPacket",
        f"- packet_id={packet_id}",
        f"- episode_id={getattr(request, 'episode_id', '') or '<none>'}",
        f"- loop_id={getattr(request, 'loop_id', '') or '<none>'}",
        f"- source_refs={_csv(source_refs)}",
        f"- protected_head_count={getattr(result, 'protected_head_count', 0)}",
        f"- protected_tail_count={getattr(result, 'protected_tail_count', 0)}",
        f"- protected_ranges={_csv(protected_ranges)}",
        f"- selected_raw_count={len(selected_raw_ids) or getattr(result, 'semantic_anchor_selected_count', 0)}",
        f"- selected_raw_ids={_csv(selected_raw_ids)}",
        f"- compacted_middle_count={getattr(result, 'compacted_line_count', 0)}",
        f"- token_budget={getattr(result, 'before_tokens', 0)}->{getattr(result, 'after_tokens', 0)}",
        f"- summary_hash={summary_hash}",
        f"- summary={_single_line(summary)}",
    )
    return EpisodeContinuityPacket(packet_id=packet_id, text="\n".join(lines), source_refs=source_refs)


def compaction_step_metadata(
    *,
    packet: EpisodeContinuityPacket,
    result: Any,
    source_step_ids: tuple[str, ...],
) -> dict[str, str]:
    summary_hash = str(getattr(result, "summary_hash", "") or "").strip() or "<none>"
    return {
        "packet_id": packet.packet_id,
        "source_step_ids": _csv(source_step_ids),
        "protected_ranges": _csv(tuple(getattr(result, "protected_ranges", ()) or ())),
        "selected_raw_ids": _csv(tuple(getattr(result, "selected_raw_ids", ()) or ())),
        "summary_hash": summary_hash,
        "token_budget_before": str(getattr(result, "before_tokens", 0) or 0),
        "token_budget_after": str(getattr(result, "after_tokens", 0) or 0),
        "compaction_query": _single_line(str(getattr(result, "compaction_query", "") or "")) or "<none>",
    }


def append_episode_continuity_packet(context: ContextBundle, packet: EpisodeContinuityPacket) -> ContextBundle:
    rendered = str(context.rendered_prompt or "").strip()
    updated_rendered = packet.text if not rendered else f"{rendered}\n\n{packet.text}"
    return replace(
        context,
        prompt_envelope=context.prompt_envelope.append_loop_context(packet.text),
        rendered_prompt=updated_rendered,
    )


def _csv(values: tuple[object, ...], *, separator: str = ", ") -> str:
    cleaned = tuple(str(value).strip() for value in values if str(value).strip())
    return separator.join(cleaned) if cleaned else "<none>"


def _single_line(value: str) -> str:
    return " ".join(str(value).split())


def retry_context_after_provider_overflow(
    *,
    error: RuntimeError,
    dependencies: Any,
    request: Any,
    profile: Any,
    session: Any,
    state_focus: Any,
    work_items: tuple[Any, ...],
    recall_items: tuple[Any, ...],
    decision: Any,
    plan: Any,
    continuity: Any,
    stage: Any,
    context_for_generation: Any,
    recovery_scope_reason: str,
    source_step_ids: tuple[str, ...],
) -> ContextCompactionOutcome | None:
    if not looks_like_context_overflow(error):
        return None
    compact = getattr(dependencies.context, "force_projection_compaction", None)
    if not callable(compact):
        return None
    result = compact(reason="provider-overflow")
    if result is None or not bool(getattr(result, "compacted", False)):
        return None
    stage("context-compact", projection_compaction_detail(result))
    flush_projection_cache(dependencies.context)
    rebuilt = dependencies.context.assemble(session, work_items, recall_items, state_focus=state_focus)
    stage(
        "context",
        f"bundle={rebuilt.bundle_id} budget={rebuilt.token_budget} recovery_scope_reason={recovery_scope_reason}",
    )
    enriched = context_for_generation(
        request=request,
        profile=profile,
        session=session,
        state_focus=state_focus,
        work_items=work_items,
        recall_items=recall_items,
        context=rebuilt,
        decision=decision,
        plan=plan,
        continuity=continuity,
    )
    packet = episode_continuity_packet(
        request=request,
        result=result,
        source_step_ids=source_step_ids,
    )
    return ContextCompactionOutcome(
        context=append_episode_continuity_packet(enriched, packet),
        result=result,
        packet=packet,
    )


__all__ = [
    "ContextCompactionOutcome",
    "EpisodeContinuityPacket",
    "append_episode_continuity_packet",
    "compact_context_after_usage",
    "compaction_step_metadata",
    "flush_projection_cache",
    "latest_compacted_projection",
    "looks_like_context_overflow",
    "projection_compaction_detail",
    "retry_context_after_provider_overflow",
    "stage_context_projection",
    "stage_context_usage",
]
