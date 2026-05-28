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
PATH_STEP_RUN_STATUSES = frozenset(
    {"queued", "dispatched", "running", "completed", "failed", "cancelled"}
)
PATH_STEP_COMMENT_AUTHOR_KINDS = frozenset({"user", "elephant", "system"})
PATH_STEP_COMMENT_TYPES = frozenset({"comment", "run_output", "status", "system"})
UNDERSTANDING_CHECK_STATUSES = frozenset(
    {"pending", "understood", "needs_clarification", "skipped"}
)


def path_step_status_after_learning_summary(status: str) -> str:
    """Return the review status after a baby elephant attaches a summary."""
    if status in {"done", "dropped"}:
        return status
    return "checking"


def path_step_status_after_understanding_check(status: str, check_status: str) -> str:
    """Return the next Flow status after the human checkpoint is updated."""
    if check_status in {"understood", "skipped"} and status in {"next", "moving", "checking", "stuck"}:
        return "done"
    if check_status == "needs_clarification" and status in {"checking", "done"}:
        return "stuck"
    return status


def path_step_status_after_run(status: str, run_status: str) -> str:
    """Return the Flow status implied by a durable baby-elephant run."""
    if status in {"done", "dropped"}:
        return status
    if run_status in {"queued", "dispatched", "running"}:
        return "moving"
    if run_status == "completed":
        return "checking"
    if run_status in {"failed", "cancelled"}:
        return "stuck"
    return status


@dataclass(frozen=True, slots=True)
class PathRecord:
    path_id: str
    personal_model_id: str
    title: str
    description: str = ""
    status: str = "active"
    priority: str = "normal"
    review_mode: str = "trusted"
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
class PathStepRunRecord:
    run_id: str
    path_step_id: str
    path_id: str
    personal_model_id: str
    status: str = "queued"
    attempt: int = 1
    max_attempts: int = 3
    parent_run_id: str = ""
    assignee_elephant_id: str = ""
    runtime_id: str = ""
    claim_token: str = ""
    session_id: str = ""
    work_dir: str = ""
    progress_stage: str = ""
    progress_detail: str = ""
    progress_current: int = 0
    progress_total: int = 0
    failure_reason: str = ""
    created_at: datetime | None = None
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    lease_expires_at: datetime | None = None
    finished_at: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.run_id, name="path step run id")
        _ensure_non_empty_text(self.path_step_id, name="path step run step id")
        _ensure_non_empty_text(self.path_id, name="path step run path id")
        _ensure_non_empty_text(self.personal_model_id, name="path step run personal model id")
        if self.status not in PATH_STEP_RUN_STATUSES:
            raise ValueError(
                f"path step run status must be one of {sorted(PATH_STEP_RUN_STATUSES)}: {self.status}"
            )
        if self.attempt < 1:
            raise ValueError("path step run attempt must be positive")
        if self.max_attempts < 1:
            raise ValueError("path step run max_attempts must be positive")
        if self.progress_current < 0 or self.progress_total < 0:
            raise ValueError("path step run progress values must be non-negative")


@dataclass(frozen=True, slots=True)
class PathStepCommentRecord:
    comment_id: str
    path_step_id: str
    path_id: str
    personal_model_id: str
    body: str
    author_kind: str = "user"
    author_id: str = ""
    comment_type: str = "comment"
    run_id: str = ""
    parent_comment_id: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.comment_id, name="path step comment id")
        _ensure_non_empty_text(self.path_step_id, name="path step comment step id")
        _ensure_non_empty_text(self.path_id, name="path step comment path id")
        _ensure_non_empty_text(self.personal_model_id, name="path step comment personal model id")
        _ensure_non_empty_text(self.body, name="path step comment body")
        if self.author_kind not in PATH_STEP_COMMENT_AUTHOR_KINDS:
            raise ValueError(
                f"path step comment author_kind must be one of {sorted(PATH_STEP_COMMENT_AUTHOR_KINDS)}: {self.author_kind}"
            )
        if self.comment_type not in PATH_STEP_COMMENT_TYPES:
            raise ValueError(
                f"path step comment_type must be one of {sorted(PATH_STEP_COMMENT_TYPES)}: {self.comment_type}"
            )


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
    "PATH_STEP_COMMENT_AUTHOR_KINDS",
    "PATH_STEP_COMMENT_TYPES",
    "PATH_STEP_RUN_STATUSES",
    "PATH_STEP_STATUSES",
    "PathRecord",
    "PathStepCommentRecord",
    "PathStepRecord",
    "PathStepRunRecord",
    "UNDERSTANDING_CHECK_STATUSES",
    "UnderstandingCheckRecord",
    "path_step_status_after_learning_summary",
    "path_step_status_after_run",
    "path_step_status_after_understanding_check",
]
