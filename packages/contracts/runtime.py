"""Core shared contract shapes.

The goal here is to define durable, serializable records for the runtime.
These shapes are intentionally plain so the rest of the system can depend on
them without creating import cycles or backend-specific coupling.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Mapping


def _ensure_unique_ids(values: tuple[str, ...], *, name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{name} ids must be unique")


def _ensure_non_empty_text(value: str, *, name: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{name} must not be empty")


_ALLOWED_STATE_FOCUS_MODES = frozenset({"embedded", "skip"})
_ALLOWED_INDEX_REFRESH_SCOPES = frozenset({"noop", "full"})
_ALLOWED_STATE_FOCUS_FAMILIES = frozenset({"execution", "exploration", "creation", "reference", "personal_model", "resume"})
_ALLOWED_STATE_FOCUS_CANDIDATE_KINDS = frozenset({"work_item"})
_ALLOWED_CONTINUITY_SIGNALS = frozenset({"none", "continue", "resume", "interrupted", "inherit"})
_ALLOWED_FOCUS_SCOPES = frozenset({"episode", "lineage", "state", "personal_model"})
_ALLOWED_BUDGET_CLASSES = frozenset({"narrow", "standard", "broad"})
_ALLOWED_STATE_FOCUS_DEGRADATION_MODES = frozenset({"none", "skip", "embedding-unavailable", "conservative"})
_ALLOWED_FOCUS_ASSIST_OUTCOMES = frozenset(
    {"not-requested", "confirmed", "suggested", "unresolved", "unsupported", "error"}
)


@dataclass(frozen=True, slots=True)
class GenerationModelProfile:
    profile_id: str
    provider_id: str
    model_id: str
    base_url: str | None = None
    transport_id: str | None = None
    reasoning_effort: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.profile_id, name="generation model profile_id")
        _ensure_non_empty_text(self.provider_id, name="generation model provider_id")
        _ensure_non_empty_text(self.model_id, name="generation model model_id")


@dataclass(frozen=True, slots=True)
class SupportModelProfile:
    profile_id: str
    provider_id: str
    model_id: str
    base_url: str | None = None
    transport_id: str | None = None
    reasoning_effort: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.profile_id, name="support model profile_id")
        _ensure_non_empty_text(self.provider_id, name="support model provider_id")
        _ensure_non_empty_text(self.model_id, name="support model model_id")


@dataclass(frozen=True, slots=True)
class RuntimeModelChoice:
    strong_model: GenerationModelProfile
    weak_model: SupportModelProfile
    state_focus_mode: str = "skip"

    def __post_init__(self) -> None:
        normalized_mode = self.state_focus_mode.strip().lower()
        if normalized_mode not in _ALLOWED_STATE_FOCUS_MODES:
            raise ValueError(
                f"state_focus_mode must be one of {sorted(_ALLOWED_STATE_FOCUS_MODES)}: {self.state_focus_mode}"
            )


@dataclass(frozen=True, slots=True)
class PersonalModelRuntimeState:
    profile_id: str
    display_name: str
    mode: str
    elephant_path: str | None = None
    preferences: tuple[str, ...] = ()
    enabled_capabilities: tuple[str, ...] = ()
    # Learning configuration, chosen at `elephant init`. Drives the Curiosity
    # subsystem's idle-ask cadence. See ADR-0004.
    learning_intensity: str = "medium"
    # Committed-tier facts loaded every session and rendered grouped by lens
    # in the frozen_prefix committed PM block. See ADR-0001 and ADR-0003.
    facts: tuple = ()


@dataclass(frozen=True, slots=True)
class ElephantIdentityRecord:
    elephant_id: str
    profile_id: str
    display_name: str
    identity_mode: str
    personality_preset: str
    initiative: str
    relational_stance: str
    working_style_contract: str
    elephant_identity_text: str | None = None
    governance_flags: tuple[str, ...] = ()
    source_manifest_path: str | None = None
    source_elephant_path: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# DEPRECATED: EpisodeState is now Episode (from packages.contracts.layers).
# This alias exists only as a migration bridge — do not use in new code.
from packages.contracts.layers import Episode as EpisodeState  # noqa: F401


@dataclass(frozen=True, slots=True)
class LearningJob:
    job_id: str
    job_type: str
    trigger: str
    status: str
    personal_model_id: str
    state_id: str
    episode_id: str
    loop_id: str | None = None
    summary: str = ""
    progress_stage: str = ""
    progress_detail: str = ""
    attempt_count: int = 0
    max_attempts: int = 3
    available_at: datetime | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    worker_id: str | None = None
    last_error: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    result_json: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EpisodeContinuityState:
    episode_id: str
    mode: str
    origin_episode_id: str
    lineage_episode_ids: tuple[str, ...] = ()
    inherited_interruption_state: str | None = None
    summary: str = ""

    @property
    def requires_recovery(self) -> bool:
        return self.mode != "foreground"


@dataclass(frozen=True, slots=True)
class PersonalModelGrowthState:
    profile_id: str
    growth_score: int = 0
    total_dialogues: int = 0
    total_tokens: int = 0
    total_experiences: int = 0
    promoted_experiences: int = 0
    active_days: int = 0
    streak_days: int = 0
    first_dialogue_at: datetime | None = None
    last_dialogue_at: datetime | None = None
    last_active_day: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StateFocusReason:
    code: str
    detail: str
    weight: float = 0.0

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.code, name="state focus reason code")
        _ensure_non_empty_text(self.detail, name="state focus reason detail")


@dataclass(frozen=True, slots=True)
class StateFocusCandidate:
    candidate_id: str
    kind: str
    label: str
    summary: str
    cache_key: str = ""
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.candidate_id, name="state focus candidate id")
        if self.kind not in _ALLOWED_STATE_FOCUS_CANDIDATE_KINDS:
            raise ValueError(
                f"state focus candidate kind must be one of {sorted(_ALLOWED_STATE_FOCUS_CANDIDATE_KINDS)}: {self.kind}"
            )
        _ensure_non_empty_text(self.label, name="state focus candidate label")
        _ensure_non_empty_text(self.summary, name="state focus candidate summary")

    @property
    def resolved_cache_key(self) -> str:
        cache_key = self.cache_key.strip()
        return cache_key or self.candidate_id


@dataclass(frozen=True, slots=True)
class StateFocusCandidateScore:
    candidate_id: str
    kind: str
    label: str
    total_score: float
    heuristics_score: float = 0.0
    embedding_score: float = 0.0
    reasons: tuple[StateFocusReason, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.candidate_id, name="state focus candidate score id")
        if self.kind not in _ALLOWED_STATE_FOCUS_CANDIDATE_KINDS:
            raise ValueError(
                f"state focus candidate score kind must be one of {sorted(_ALLOWED_STATE_FOCUS_CANDIDATE_KINDS)}: {self.kind}"
            )
        _ensure_non_empty_text(self.label, name="state focus candidate score label")


@dataclass(frozen=True, slots=True)
class StateFocusDecision:
    focus_family: str
    confidence: float
    focus_work_item_ids: tuple[str, ...] = ()
    provisional_work_item_seed: str | None = None
    continuity_signal: str = "none"
    focus_scope: str = "episode"
    context_budget: str = "standard"
    embedding_available: bool = False
    degradation_mode: str = "none"
    needs_focus_model_assist: bool = False
    focus_assist_outcome: str = "not-requested"
    selection_path: str = "direct"
    reasons: tuple[StateFocusReason, ...] = ()
    candidate_scores: tuple[StateFocusCandidateScore, ...] = ()
    audit_trace: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.focus_family not in _ALLOWED_STATE_FOCUS_FAMILIES:
            raise ValueError(f"focus_family must be one of {sorted(_ALLOWED_STATE_FOCUS_FAMILIES)}: {self.focus_family}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("state focus confidence must stay between 0.0 and 1.0")
        if self.continuity_signal not in _ALLOWED_CONTINUITY_SIGNALS:
            raise ValueError(
                f"continuity_signal must be one of {sorted(_ALLOWED_CONTINUITY_SIGNALS)}: {self.continuity_signal}"
            )
        if self.focus_scope not in _ALLOWED_FOCUS_SCOPES:
            raise ValueError(
                f"focus_scope must be one of {sorted(_ALLOWED_FOCUS_SCOPES)}: {self.focus_scope}"
            )
        if self.context_budget not in _ALLOWED_BUDGET_CLASSES:
            raise ValueError(
                f"context_budget must be one of {sorted(_ALLOWED_BUDGET_CLASSES)}: {self.context_budget}"
            )
        if self.degradation_mode not in _ALLOWED_STATE_FOCUS_DEGRADATION_MODES:
            raise ValueError(
                "degradation_mode must be one of "
                f"{sorted(_ALLOWED_STATE_FOCUS_DEGRADATION_MODES)}: {self.degradation_mode}"
            )
        if self.focus_assist_outcome not in _ALLOWED_FOCUS_ASSIST_OUTCOMES:
            raise ValueError(
                "focus_assist_outcome must be one of "
                f"{sorted(_ALLOWED_FOCUS_ASSIST_OUTCOMES)}: {self.focus_assist_outcome}"
            )
        _ensure_non_empty_text(self.selection_path, name="state focus selection path")
        _ensure_unique_ids(self.focus_work_item_ids, name="state focus work item")
        _ensure_unique_ids(
            tuple(score.candidate_id for score in self.candidate_scores),
            name="state focus candidate score",
        )

    @property
    def primary_focus_work_item_id(self) -> str | None:
        if not self.focus_work_item_ids:
            return None
        return self.focus_work_item_ids[0]


@dataclass(frozen=True, slots=True)
class StateFocusResolutionRequest:
    prompt: str
    episode_id: str
    personal_model_id: str
    elephant_id: str | None = None
    continuity: EpisodeContinuityState | None = None
    previous_decision: StateFocusDecision | None = None
    surface_hints: tuple[str, ...] = ()
    artifact_hints: tuple[str, ...] = ()
    recent_turn_summaries: tuple[str, ...] = ()
    relationship_hints: tuple[str, ...] = ()
    work_item_candidates: tuple[StateFocusCandidate, ...] = ()
    model_choice: RuntimeModelChoice | None = None
    embedding_available: bool = False


@dataclass(frozen=True, slots=True)
class StructuredTurnSlot:
    summary: str = ""
    detail: tuple[str, ...] = ()
    compression: str = "structured"
    provenance: str = ""
    source_refs: tuple[str, ...] = ()
    linkage_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StepReplayRecord:
    turn_id: str
    episode_id: str
    source: str
    observation: StructuredTurnSlot
    reasoning: StructuredTurnSlot
    action: StructuredTurnSlot
    outcome: StructuredTurnSlot
    personal_model_id: str | None = None
    elephant_id: str | None = None
    source_event_id: str | None = None
    reasoning_availability: str = "summary_only"
    reasoning_provenance: str = "runtime.decision_summary"
    compression_tier: str = "raw_turn"
    work_item_ids: tuple[str, ...] = ()
    source_turn_ids: tuple[str, ...] = ()
    correction_evidence_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RecallEvidence:
    evidence_id: str
    episode_id: str
    kind: str
    content: str
    source_id: str = ""
    source_kind: str = "semantic_index"
    semantic_index_entry_id: str | None = None
    step_id: str | None = None
    loop_id: str | None = None
    work_item_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    created_at: datetime | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExperienceRecord:
    experience_id: str
    episode_id: str
    personal_model_id: str
    elephant_id: str | None
    kind: str
    title: str
    summary: str
    status: str
    run_id: str | None = None
    source_event_id: str | None = None
    work_item_id: str | None = None
    tool_call_count: int = 0
    model_turn_count: int = 0
    related_skill_ids: tuple[str, ...] = ()
    produced_artifact_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuntimeArtifact:
    artifact_id: str
    episode_id: str
    kind: str
    name: str
    uri: str
    checksum: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuntimeEvidenceBundle:
    episode_id: str
    recall_items: tuple[RecallEvidence, ...] = ()
    artifacts: tuple[RuntimeArtifact, ...] = ()

    def __post_init__(self) -> None:
        _ensure_unique_ids(tuple(item.evidence_id for item in self.recall_items), name="recall evidence")
        _ensure_unique_ids(tuple(artifact.artifact_id for artifact in self.artifacts), name="artifact")
        for item in self.recall_items:
            if item.episode_id != self.episode_id:
                raise ValueError("every recall item must reference the same episode")
        for artifact in self.artifacts:
            if artifact.episode_id != self.episode_id:
                raise ValueError("every artifact must reference the same episode")


@dataclass(frozen=True, slots=True)
class RecallReason:
    code: str
    detail: str
    weight: float = 0.0


@dataclass(frozen=True, slots=True)
class RecallReasons:
    opened_scopes: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    scope_reason: str = ""
    rerank_summary: str = ""
    reasons: tuple[RecallReason, ...] = ()
    # Cache-first retrieval status for the query vector. One of:
    #   "hit"             — query vector was served from the embedding cache
    #   "miss-backfilled" — cache miss; background backfill queued for next turn
    #   "pending"         — an embedding is already in-flight; not waited on
    #   "disabled"        — caller passed allow_embeddings=False
    #   "unavailable"     — embedding runtime not loaded (cold or failed)
    #   ""                — retrieval did not evaluate an embedding path
    vector_cache_status: str = ""


@dataclass(frozen=True, slots=True)
class EvidenceRetrievalRequest:
    episode_id: str
    personal_model_id: str
    elephant_id: str | None = None
    lineage_episode_ids: tuple[str, ...] = ()
    work_item_ids: tuple[str, ...] = ()
    query: str = ""
    scopes: tuple[str, ...] = ("episode",)
    latency_mode: str = "balanced"
    limit: int = 5
    include_inactive: bool = False
    explain: bool = True
    scope_reason: str = ""
    relationship_hints: tuple[str, ...] = ()
    target_slots: tuple[str, ...] = ()
    max_compression: str = "episode_summary"
    replay_mode: str = "off"
    state_focus: StateFocusDecision | None = None
    allow_embeddings: bool = True


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    evidence_id: str
    evidence: RecallEvidence
    score: float
    lexical_score: float = 0.0
    vector_score: float = 0.0
    graph_score: float = 0.0
    matched_scopes: tuple[str, ...] = ()
    reasons: tuple[RecallReason, ...] = ()
    embedding_mode: str = ""
    replay_record: StepReplayRecord | None = None
    replay_slots: tuple[str, ...] = ()
    replay_summary: str = ""


@dataclass(frozen=True, slots=True)
class EmbeddingIndexInvalidation:
    evidence_id: str
    lifecycle_state: str
    stale_cache_key: str
    replacement_evidence_id: str | None = None
    refresh_action: str = "drop"
    reason: str = ""


@dataclass(frozen=True, slots=True)
class EmbeddingIndexRebuildPlan:
    target: str
    refresh_scope: str
    active_evidence_ids: tuple[str, ...] = ()
    active_cache_keys: tuple[str, ...] = ()
    stale_cache_keys: tuple[str, ...] = ()
    replacement_evidence_ids: tuple[str, ...] = ()
    dimensions: tuple[int, ...] = ()
    steps: tuple[str, ...] = ()
    summary: str = ""

    def __post_init__(self) -> None:
        if self.refresh_scope not in _ALLOWED_INDEX_REFRESH_SCOPES:
            raise ValueError(
                f"embedding index refresh_scope must be one of {sorted(_ALLOWED_INDEX_REFRESH_SCOPES)}: {self.refresh_scope}"
            )


@dataclass(frozen=True, slots=True)
class EmbeddingIndexPolicy:
    model_id: str
    lexical_index_version: str
    embedding_index_version: str
    active_dimensions: tuple[int, ...] = ()
    tracked_evidence_count: int = 0
    rebuild_required: bool = False
    invalidated_evidence_ids: tuple[str, ...] = ()
    invalidation_reason: str = ""
    invalidations: tuple[EmbeddingIndexInvalidation, ...] = ()
    rebuild_plan: EmbeddingIndexRebuildPlan | None = None


@dataclass(frozen=True, slots=True)
class EvidenceRetrievalResult:
    request: EvidenceRetrievalRequest
    scope_episode_ids: tuple[str, ...]
    scope_reason: str
    candidates: tuple[EvidenceCandidate, ...]
    recall_reasons: RecallReasons
    index_policy: EmbeddingIndexPolicy


@dataclass(frozen=True, slots=True)
class ResumePacket:
    episode_id: str
    personal_model_id: str
    elephant_id: str | None
    focus_work_item_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    constraint_ids: tuple[str, ...] = ()
    summary: str = ""
    next_move: str = ""
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProcedureStep:
    step_id: str
    title: str
    instruction: str
    tool_name: str | None = None


@dataclass(frozen=True, slots=True)
class ProcedureRecord:
    procedure_id: str
    title: str
    summary: str
    status: str
    trigger_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    verification_bundle_id: str | None = None
    skill_id: str | None = None
    steps: tuple[ProcedureStep, ...] = ()

    def __post_init__(self) -> None:
        _ensure_unique_ids(tuple(step.step_id for step in self.steps), name="procedure step")


@dataclass(frozen=True, slots=True)
class ProcedureLibrary:
    profile_id: str
    procedures: tuple[ProcedureRecord, ...] = ()

    def __post_init__(self) -> None:
        _ensure_unique_ids(tuple(procedure.procedure_id for procedure in self.procedures), name="procedure")


@dataclass(frozen=True, slots=True)
class PromptMessage:
    """Provider-neutral chat message used by live prompt projections."""

    role: str
    content: str = ""
    name: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_calls: tuple[Mapping[str, object], ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PromptEnvelope:
    """Structured prompt sections used by live model requests."""

    frozen_prefix: str = ""
    session_snapshot: str = ""
    loop_context: str = ""
    messages: tuple[PromptMessage, ...] = ()

    def system_prompt(self) -> str:
        return "\n\n".join(
            section
            for section in (self.frozen_prefix.strip(), self.session_snapshot.strip())
            if section
        )

    def user_prelude(self) -> str:
        return self.loop_context.strip()

    def combined_prompt(self) -> str:
        return "\n\n".join(
            section
            for section in (
                self.frozen_prefix.strip(),
                self.session_snapshot.strip(),
                self.loop_context.strip(),
            )
            if section
        )

    def append_loop_context(self, text: str) -> "PromptEnvelope":
        normalized = str(text).strip()
        if not normalized:
            return self
        current = self.loop_context.strip()
        updated = normalized if not current else f"{current}\n\n{normalized}"
        return PromptEnvelope(
            frozen_prefix=self.frozen_prefix,
            session_snapshot=self.session_snapshot,
            loop_context=updated,
            messages=self.messages,
        )


@dataclass(frozen=True, slots=True)
class ContextBundle:
    bundle_id: str
    episode_id: str
    instruction_refs: tuple[str, ...] = ()
    work_item_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    token_budget: int = 0
    prompt_envelope: PromptEnvelope = field(default_factory=PromptEnvelope)
    rendered_prompt: str | None = None


@dataclass(frozen=True, slots=True)
class PlanStep:
    step_id: str
    title: str
    rationale: str
    dependency_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanDraft:
    plan_id: str
    work_item_id: str
    episode_id: str
    steps: tuple[PlanStep, ...] = ()
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    execution_id: str
    episode_id: str
    outcome: str
    summary: str
    reasoning: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_prompt_tokens: int = 0
    cache_creation_prompt_tokens: int = 0
    cache_usage_reported: bool = False
    produced_artifact_ids: tuple[str, ...] = ()
    telemetry_event_ids: tuple[str, ...] = ()
    trace_metadata: Mapping[str, str] = field(default_factory=dict)
    side_effects: tuple[str, ...] = ()
    tool_calls: tuple["ExecutionToolCall", ...] = ()

    @property
    def session_id(self) -> str:
        return self.episode_id


@dataclass(frozen=True, slots=True)
class ExecutionToolCall:
    tool_name: str
    arguments: dict[str, object] = field(default_factory=dict)
    call_id: str = ""


_ALLOWED_WAIT_CONDITION_KINDS = frozenset(
    {
        "timer",
        "event",
        "tool_callback",
        "network",
        "approval",
        "external_poll",
        "budget_exhausted",
    }
)


@dataclass(frozen=True, slots=True)
class WaitCondition:
    """Structured park reason.

    Long-horizon runs park a Loop when they cannot make progress right now.
    The runtime consumes ``wait_condition.kind`` to decide how to wake the
    Loop back up (timer, event bus, tool callback, network probe, approval,
    external poll, or budget rollover). ``payload`` carries arbitrary
    key/value hints for the resume path.
    """

    kind: str
    payload: Mapping[str, str] = field(default_factory=dict)
    wake_at: datetime | None = None
    event_topic: str | None = None
    event_match: Mapping[str, str] | None = None
    tool_handle_id: str | None = None
    created_at: datetime | None = None
    auto_wake: bool = True

    def __post_init__(self) -> None:
        kind = str(self.kind or "").strip()
        if kind not in _ALLOWED_WAIT_CONDITION_KINDS:
            raise ValueError(
                f"wait condition kind must be one of {sorted(_ALLOWED_WAIT_CONDITION_KINDS)}: {self.kind!r}"
            )


@dataclass(frozen=True, slots=True)
class RetryState:
    """Retry bookkeeping persisted alongside a LoopState.

    Used so a resume path can replay the same provider or tool call with a
    stable idempotency key, respect a remaining ``Retry-After`` deadline, and
    bound attempts across crashes.
    """

    attempt: int = 0
    last_error_kind: str = ""
    last_error_detail: str = ""
    next_retry_at: datetime | None = None
    idempotency_key: str | None = None


_ALLOWED_PENDING_TOOL_CALL_STATUSES = frozenset({"dispatched", "running", "done_unread"})


@dataclass(frozen=True, slots=True)
class PendingToolCall:
    """One tool call that has left the kernel but has not been reconciled yet.

    ``dispatched``   — sent into the tool, no result observed;
                       on resume, replay with the stored ``idempotency_key``
                       (or, if a completed Step already exists, skip the
                       replay to stay idempotent).
    ``running``      — async tool handle is in flight; resume polls the handle.
    ``done_unread``  — result already on disk but the model has not seen it
                       in its observation stream; resume injects it.
    """

    call_id: str
    tool_name: str
    arguments: Mapping[str, object]
    started_at: datetime
    step_id: str
    handle_id: str | None = None
    status: str = "dispatched"
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        status = str(self.status or "").strip()
        if status not in _ALLOWED_PENDING_TOOL_CALL_STATUSES:
            raise ValueError(
                f"pending tool call status must be one of "
                f"{sorted(_ALLOWED_PENDING_TOOL_CALL_STATUSES)}: {self.status!r}"
            )


_LOOP_STATE_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class LoopState:
    run_id: str
    episode_id: str
    source_event_id: str
    prompt: str
    status: str
    phase: str
    step_count: int
    model_turn_count: int
    tool_call_count: int
    max_model_turns: int
    max_wall_time_seconds: int
    created_at: datetime
    updated_at: datetime
    waiting_reason: str | None = None
    continuation_prompt: str | None = None
    last_summary: str | None = None
    # --- schema v2 additions (all defaulted; v1 rows load via migrator) ---
    schema_version: int = _LOOP_STATE_SCHEMA_VERSION
    wait_condition: WaitCondition | None = None
    pending_tool_calls: tuple[PendingToolCall, ...] = ()
    partial_assistant: str | None = None
    context_bundle_id: str | None = None
    active_evidence_refs: tuple[str, ...] = ()
    retry_state: RetryState | None = None
    heartbeat_at: datetime | None = None
    crash_marker: str | None = None


@dataclass(frozen=True, slots=True)
class LoopStep:
    step_id: str
    run_id: str
    episode_id: str
    step_index: int
    kind: str
    title: str
    content: str
    created_at: datetime
    outcome: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: str
    event_type: str
    episode_id: str
    source: str
    payload: dict[str, str] = field(default_factory=dict)
