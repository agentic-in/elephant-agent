"""Trajectory-based skill optimization helpers for reflect agents."""

from .aggregation import aggregate_signals, build_candidate_key, load_existing_candidate_statuses
from .lifecycle import (
    apply_approved_optimization,
    compose_updated_instruction,
    find_candidate_by_ref,
    find_candidate_by_topic,
    find_candidate_ref,
    load_candidates,
    mark_candidate_review_status,
    optimization_candidate_metadata,
    optimization_candidate_text,
    optimization_candidate_topic,
    persisted_candidate_from_fact,
    persist_optimization_candidate,
    should_suppress_candidate,
    write_optimization_candidate,
)
from .trajectory_signals import (
    detect_error_recoveries,
    detect_recurring_sequences,
    detect_tool_combinations,
    extract_tool_sequences,
    extract_trajectory_signals,
    load_recent_closed_episodes,
)
from .types import PersistedOptimizationCandidate, SkillOptimizationCandidate, ToolTrajectorySignal

__all__ = [
    "PersistedOptimizationCandidate",
    "SkillOptimizationCandidate",
    "ToolTrajectorySignal",
    "aggregate_signals",
    "apply_approved_optimization",
    "build_candidate_key",
    "compose_updated_instruction",
    "detect_error_recoveries",
    "detect_recurring_sequences",
    "detect_tool_combinations",
    "extract_tool_sequences",
    "extract_trajectory_signals",
    "find_candidate_by_ref",
    "find_candidate_by_topic",
    "find_candidate_ref",
    "load_candidates",
    "load_existing_candidate_statuses",
    "load_recent_closed_episodes",
    "mark_candidate_review_status",
    "optimization_candidate_metadata",
    "optimization_candidate_text",
    "optimization_candidate_topic",
    "persisted_candidate_from_fact",
    "persist_optimization_candidate",
    "should_suppress_candidate",
    "write_optimization_candidate",
]
