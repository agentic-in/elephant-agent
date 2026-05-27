"""Durable user-facing Path contracts.

These records sit above the canonical Episode/Loop/Step execution trail. A
Path is something Elephant can help shape over time: a work project, health
plan, learning arc, habit, or any other long-running direction in the user's
life.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from .layers import _ensure_non_empty_text


PATH_STATUSES = frozenset({"active", "paused", "completed", "dropped"})
PATH_REVIEW_MODES = frozenset({"ask_first", "trusted"})
PATH_STEP_STATUSES = frozenset(
    {"later", "next", "moving", "checking", "done", "stuck", "dropped"}
)
UNDERSTANDING_CHECK_STATUSES = frozenset(
    {"pending", "understood", "needs_clarification", "skipped"}
)


@dataclass(frozen=True, slots=True)
class PathRecord:
    path_id: str
    personal_model_id: str
    title: str
    description: str = ""
    status: str = "active"
    priority: str = "normal"
    review_mode: str = "ask_first"
    owner_elephant_id: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.path_id, name="path id")
        _ensure_non_empty_text(self.personal_model_id, name="path personal model id")
        _ensure_non_empty_text(self.title, name="path title")
        if self.status not in PATH_STATUSES:
            raise ValueError(f"path status must be one of {sorted(PATH_STATUSES)}: {self.status}")
        if self.review_mode not in PATH_REVIEW_MODES:
            raise ValueError(
                f"path review mode must be one of {sorted(PATH_REVIEW_MODES)}: {self.review_mode}"
            )


@dataclass(frozen=True, slots=True)
class PathStepRecord:
    path_step_id: str
    path_id: str
    personal_model_id: str
    title: str
    description: str = ""
    status: str = "next"
    order_index: int = 0
    assignee_elephant_id: str = ""
    creator_elephant_id: str = ""
    due_at: datetime | None = None
    related_episode_id: str | None = None
    related_loop_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.path_step_id, name="path step id")
        _ensure_non_empty_text(self.path_id, name="path step path id")
        _ensure_non_empty_text(self.personal_model_id, name="path step personal model id")
        _ensure_non_empty_text(self.title, name="path step title")
        if self.status not in PATH_STEP_STATUSES:
            raise ValueError(
                f"path step status must be one of {sorted(PATH_STEP_STATUSES)}: {self.status}"
            )
        if self.order_index < 0:
            raise ValueError("path step order_index must be non-negative")


@dataclass(frozen=True, slots=True)
class LearningSummaryRecord:
    summary_id: str
    path_step_id: str
    path_id: str
    run_id: str = ""
    summary_type: str = "task"
    what_done: str = ""
    why_it_matters: str = ""
    how_it_was_done: str = ""
    knowledge: str = ""
    human_takeaway: str = ""
    created_by_elephant_id: str = ""
    created_at: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.summary_id, name="learning summary id")
        _ensure_non_empty_text(self.path_step_id, name="learning summary path step id")
        _ensure_non_empty_text(self.path_id, name="learning summary path id")


@dataclass(frozen=True, slots=True)
class UnderstandingCheckRecord:
    check_id: str
    path_step_id: str
    summary_id: str
    status: str = "pending"
    checked_by: str = "user"
    checked_at: datetime | None = None
    note: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.check_id, name="understanding check id")
        _ensure_non_empty_text(self.path_step_id, name="understanding check path step id")
        _ensure_non_empty_text(self.summary_id, name="understanding check summary id")
        if self.status not in UNDERSTANDING_CHECK_STATUSES:
            raise ValueError(
                "understanding check status must be one of "
                f"{sorted(UNDERSTANDING_CHECK_STATUSES)}: {self.status}"
            )


__all__ = [
    "LearningSummaryRecord",
    "PATH_REVIEW_MODES",
    "PATH_STATUSES",
    "PATH_STEP_STATUSES",
    "PathRecord",
    "PathStepRecord",
    "UNDERSTANDING_CHECK_STATUSES",
    "UnderstandingCheckRecord",
]
