"""Shared data types for trajectory-based skill optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ToolTrajectorySignal:
    """One deterministic signal extracted from cross-episode tool trajectories."""

    signal_id: str
    signal_type: str
    tool_names: tuple[str, ...]
    episode_ids: tuple[str, ...]
    occurrence_count: int
    confidence: float
    summary: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SkillOptimizationCandidate:
    """A candidate skill optimization derived from one or more signals."""

    candidate_id: str
    target_skill_id: str | None
    target_index_id: str | None
    optimization_type: str
    supporting_signals: tuple[str, ...]
    confidence: float
    summary: str
    suggested_action: str
    candidate_key: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PersistedOptimizationCandidate:
    """A PM fact-backed optimization candidate used by lifecycle helpers."""

    ref: str
    topic: str
    text: str
    fact_status: str
    review_status: str
    candidate_id: str
    candidate_key: str
    target_skill_id: str | None
    target_index_id: str | None
    target_scope: str | None
    optimization_type: str
    signal_type: str
    occurrence_count: int
    confidence: float
    recall_policy: str
    retention_lifecycle: str
    committed_at: str
    metadata: Mapping[str, str] = field(default_factory=dict)
