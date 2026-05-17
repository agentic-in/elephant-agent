"""Canonical system-layer contract shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping


def _ensure_non_empty_text(value: str, *, name: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{name} must not be empty")


def _ensure_text_tuple(values: tuple[str, ...], *, name: str) -> None:
    for value in values:
        if not str(value).strip():
            raise ValueError(f"{name} values must not be empty")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} values must be unique")


_STEP_PHASES = frozenset({"observation", "reasoning", "acting"})
_STEP_STATUSES = frozenset({"planned", "completed", "failed", "cancelled"})
_EPISODE_STATUSES = frozenset({"open", "paused", "closed"})


@dataclass(frozen=True, slots=True)
class PersonalModel:
    personal_model_id: str
    display_name: str = ""
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.personal_model_id, name="personal model id")


@dataclass(frozen=True, slots=True)
class State:
    state_id: str
    personal_model_id: str
    state_anchor: str
    status: str = "active"
    elephant_id: str = ""
    elephant_name: str = ""
    identity_mode: str = ""
    posture: str = ""
    capability_boundaries: tuple[str, ...] = ()
    initiative: str = ""
    working_style: str = ""
    surface_bindings: tuple[str, ...] = ()
    safety_boundaries: tuple[str, ...] = ()
    disclosure_boundaries: tuple[str, ...] = ()
    source_manifest: str = ""
    elephant_identity_text: str = ""
    summary: str = ""
    current_context_note: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.state_id, name="state id")
        _ensure_non_empty_text(self.personal_model_id, name="state personal model id")
        _ensure_non_empty_text(self.state_anchor, name="state anchor")
        _ensure_text_tuple(
            self.capability_boundaries,
            name="state capability boundaries",
        )
        _ensure_text_tuple(self.surface_bindings, name="state surface bindings")
        _ensure_text_tuple(self.safety_boundaries, name="state safety boundaries")
        _ensure_text_tuple(self.disclosure_boundaries, name="state disclosure boundaries")


@dataclass(frozen=True, slots=True)
class Episode:
    """Canonical session entity — the single source of truth for episode lifecycle.

    Status: "open" | "paused" | "closed"
    """

    episode_id: str
    state_id: str
    personal_model_id: str
    entry_surface: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    updated_at: datetime | None = None
    exit_summary: str = ""
    elephant_id: str = ""
    parent_episode_id: str | None = None
    interruption_state: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.episode_id, name="episode id")
        _ensure_non_empty_text(self.state_id, name="episode state id")
        _ensure_non_empty_text(self.personal_model_id, name="episode personal model id")
        _ensure_non_empty_text(self.entry_surface, name="episode entry surface")
        _ensure_non_empty_text(self.status, name="episode status")
        if self.status not in _EPISODE_STATUSES:
            raise ValueError(
                f"episode status must be one of {sorted(_EPISODE_STATUSES)}: {self.status}"
            )


@dataclass(frozen=True, slots=True)
class Loop:
    loop_id: str
    episode_id: str
    state_id: str
    personal_model_id: str
    trigger_type: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    summary: str = ""
    outcome: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.loop_id, name="loop id")
        _ensure_non_empty_text(self.episode_id, name="loop episode id")
        _ensure_non_empty_text(self.state_id, name="loop state id")
        _ensure_non_empty_text(self.personal_model_id, name="loop personal model id")
        _ensure_non_empty_text(self.trigger_type, name="loop trigger type")
        _ensure_non_empty_text(self.status, name="loop status")


@dataclass(frozen=True, slots=True)
class Step:
    step_id: str
    loop_id: str
    episode_id: str
    state_id: str
    personal_model_id: str
    phase: str
    action: str
    status: str
    sequence: int
    created_at: datetime
    summary: str = ""
    outcome: str = ""
    payload_refs: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.step_id, name="step id")
        _ensure_non_empty_text(self.loop_id, name="step loop id")
        _ensure_non_empty_text(self.episode_id, name="step episode id")
        _ensure_non_empty_text(self.state_id, name="step state id")
        _ensure_non_empty_text(self.personal_model_id, name="step personal model id")
        if self.phase not in _STEP_PHASES:
            raise ValueError(f"step phase must be one of {sorted(_STEP_PHASES)}: {self.phase}")
        _ensure_non_empty_text(self.action, name="step action")
        if self.status not in _STEP_STATUSES:
            raise ValueError(f"step status must be one of {sorted(_STEP_STATUSES)}: {self.status}")
        _ensure_text_tuple(self.payload_refs, name="step payload refs")
        if self.sequence < 0:
            raise ValueError("step sequence must be non-negative")
