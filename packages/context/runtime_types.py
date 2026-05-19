"""Context runtime data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from packages.contracts.runtime import ContextBundle


@dataclass(frozen=True, slots=True)
class ContextLayerBudget:
    layer_name: str
    requested_tokens: int
    allocated_tokens: int
    required: bool = False
    priority: int = 0
    omitted: bool = False
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextBudgetRequest:
    layer_name: str
    desired_tokens: int
    minimum_tokens: int = 0
    required: bool = False
    priority: int = 0
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextBudgetPlan:
    total_tokens: int
    allocations: tuple[ContextLayerBudget, ...]
    overflow_tokens: int
    omitted_layers: tuple[str, ...] = ()

    @property
    def allocated_tokens(self) -> int:
        return sum(allocation.allocated_tokens for allocation in self.allocations)

    def allocation_for(self, layer_name: str) -> ContextLayerBudget | None:
        for allocation in self.allocations:
            if allocation.layer_name == layer_name:
                return allocation
        return None


@dataclass(frozen=True, slots=True)
class ContextSummaryRequest:
    layer_name: str
    source_refs: tuple[str, ...]
    token_budget: int
    reason: str
    required: bool = False


@dataclass(frozen=True, slots=True)
class ContextRetrievalRequest:
    request_id: str
    layer_name: str
    session_id: str
    query: str
    evidence_refs: tuple[str, ...] = ()
    work_item_ids: tuple[str, ...] = ()
    token_budget: int = 0
    priority: int = 0
    reason: str = ""
    target_slots: tuple[str, ...] = ()
    max_compression: str = "episode_summary"
    replay_mode: str = "off"


@dataclass(frozen=True, slots=True)
class ContextLayerSnapshot:
    layer_name: str
    source_refs: tuple[str, ...]
    content: tuple[str, ...]
    token_budget: int
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class EpisodeFrozenContext:
    source_refs: tuple[str, ...]
    content: tuple[str, ...]
    token_budget: int


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    source_refs: tuple[str, ...]
    profile_refs: tuple[str, ...]
    work_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    content: tuple[str, ...]
    token_budget: int
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class EpisodeReplay:
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    content: tuple[str, ...]
    token_budget: int
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class LoopContext:
    source_refs: tuple[str, ...]
    content: tuple[str, ...]
    token_budget: int


@dataclass(frozen=True, slots=True)
class RequestAttachments:
    source_refs: tuple[str, ...]
    content: tuple[str, ...]
    token_budget: int


@dataclass(frozen=True, slots=True)
class EpisodeFrame:
    session_id: str
    profile_id: str
    stable_prefix: EpisodeFrozenContext
    session_snapshot: StateSnapshot
    replay_packet: EpisodeReplay | None
    loop_context: LoopContext | None
    request_attachments: RequestAttachments | None
    rationale: str = ""
    source_trace: tuple[ContextSourceTrace, ...] = ()

    def layers(self) -> tuple[ContextLayerSnapshot, ...]:
        layers = [
            ContextLayerSnapshot(
                layer_name="stable_prefix",
                source_refs=self.stable_prefix.source_refs,
                content=self.stable_prefix.content,
                token_budget=self.stable_prefix.token_budget,
            ),
            ContextLayerSnapshot(
                layer_name="session_snapshot",
                source_refs=self.session_snapshot.source_refs,
                content=self.session_snapshot.content,
                token_budget=self.session_snapshot.token_budget,
                summary=self.session_snapshot.summary,
            ),
        ]
        if self.replay_packet is not None:
            layers.append(
                ContextLayerSnapshot(
                    layer_name="replay_packet",
                    source_refs=self.replay_packet.source_refs,
                    content=self.replay_packet.content,
                    token_budget=self.replay_packet.token_budget,
                    summary=self.replay_packet.summary,
                )
            )
        if self.loop_context is not None:
            layers.append(
                ContextLayerSnapshot(
                    layer_name="loop_context",
                    source_refs=self.loop_context.source_refs,
                    content=self.loop_context.content,
                    token_budget=self.loop_context.token_budget,
                )
            )
        if self.request_attachments is not None:
            layers.append(
                ContextLayerSnapshot(
                    layer_name="request_attachments",
                    source_refs=self.request_attachments.source_refs,
                    content=self.request_attachments.content,
                    token_budget=self.request_attachments.token_budget,
                )
            )
        return tuple(layers)


@dataclass(frozen=True, slots=True)
class ContextSourceTrace:
    layer_name: str
    selected_refs: tuple[str, ...]
    reason: str
    omitted_refs: tuple[str, ...] = ()

    def describe(self) -> str:
        selected = ", ".join(self.selected_refs) if self.selected_refs else "none"
        omitted = f" | omitted: {', '.join(self.omitted_refs)}" if self.omitted_refs else ""
        return f"- {self.layer_name}: {self.reason} | selected: {selected}{omitted}"


@dataclass(frozen=True, slots=True)
class ContextAssemblyPlan:
    session_id: str
    profile_id: str
    total_tokens: int
    layers: tuple[ContextLayerSnapshot, ...]
    budgets: ContextBudgetPlan
    summary_requests: tuple[ContextSummaryRequest, ...]
    retrieval_requests: tuple[ContextRetrievalRequest, ...]
    frame: EpisodeFrame | None = None
    rationale: str = ""
    source_trace: tuple[ContextSourceTrace, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextAssemblyResult:
    bundle: ContextBundle
    plan: ContextAssemblyPlan
    rendered_prompt: str
    summary_by_layer: Mapping[str, str] = field(default_factory=dict)
    retrieved_evidence_refs: tuple[str, ...] = ()
    source_trace: tuple[ContextSourceTrace, ...] = ()
    frame: EpisodeFrame | None = None
