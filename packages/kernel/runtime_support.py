"""Canonical event-to-outcome lifecycle orchestration.

The kernel is intentionally thin: it coordinates the turn lifecycle across the
shared contracts and capability ports without embedding provider, SQL, or
delivery specifics.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import hashlib
from html import unescape as html_unescape
import json
import os
from pathlib import Path
import re
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from packages.capabilities.runtime import (
    ContextCapability,
    DeliveryAdapterCapability,
    RecallCapability,
    ModelProviderCapability,
    TelemetrySinkCapability,
    ToolCapability,
)
from packages.embeddings import EmbeddingService
from packages.security import SecurityPolicy
from packages.contracts.layers import Episode, Loop, PersonalModel, State, Step
from packages.contracts.runtime import (
    LoopState,
    LoopStep,
    ContextBundle,
    EvidenceRetrievalRequest,
    EventEnvelope,
    ExecutionResult,
    PendingToolCall,
    RetryState,
    StateFocusDecision,
    RecallEvidence,
    PlanDraft,
    PromptMessage,
    PersonalModelRuntimeState,
    WaitCondition,
)
from packages.tools.tool_result_storage import (
    ToolResultBudgetConfig,
    enforce_tool_observation_budget,
    maybe_persist_tool_result,
)

from .loop_checkpoint_support import LoopCheckpointService


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _provider_system_prompt_for_recording(context: ContextBundle) -> str:
    envelope = context.prompt_envelope
    sections: list[str] = []
    identity = envelope.system_prompt().strip()
    if identity:
        sections.append(identity)
    for message in envelope.messages:
        content = str(message.content or "").strip()
        if str(message.role or "").strip().lower() == "system" and content and content not in sections:
            sections.append(content)
    return "\n\n".join(sections)


@runtime_checkable
class KernelStoragePort(Protocol):
    """Typed storage port used by the kernel lifecycle."""

    def ensure_default_personal_model(self, *, personal_model_id: str = "you") -> PersonalModel:
        """Load or create the default PersonalModel."""

    def load_personal_model(self, personal_model_id: str) -> PersonalModel | None:
        """Load a durable PersonalModel."""

    def load_state(self, state_id: str) -> State | None:
        """Load an elephant State."""

    def current_state(self) -> State | None:
        """Load the active elephant State."""

    def create_state(
        self,
        *,
        personal_model_id: str = "you",
        elephant_name: str,
        elephant_id: str | None = None,
        state_id: str | None = None,
        state_anchor: str | None = None,
        surface_bindings: tuple[str, ...] = (),
        current_context_note: str = "",
        metadata: dict[str, str] | None = None,
    ) -> State:
        """Create an elephant State."""

    def switch_state(self, state_id: str, *, selected_at: datetime | None = None) -> State:
        """Make an elephant State active."""

    def upsert_state(
        self,
        state: State,
        *,
        updated_at: datetime | None = None,
    ) -> None:
        """Persist an elephant State."""

    def upsert_episode(self, episode: Episode) -> None:
        """Persist an Episode."""

    def load_episode(self, episode_id: str) -> Episode | None:
        """Load an Episode."""

    def list_episodes(self, *, state_id: str | None = None) -> tuple[Episode, ...]:
        """List Episodes."""

    def record_episode_transition(
        self,
        parent_episode_id: str,
        child_episode_id: str,
        transitioned_at: datetime,
        *,
        reason: str = "",
    ) -> None:
        """Record a parent-to-child Episode transition."""

    def upsert_loop(self, loop: Loop) -> None:
        """Persist a Loop."""

    def list_loops(self, *, episode_id: str | None = None) -> tuple[Loop, ...]:
        """List Loops."""

    def enqueue_learning_job(
        self,
        *,
        job_type: str,
        trigger: str,
        personal_model_id: str,
        state_id: str,
        episode_id: str,
        loop_id: str | None = None,
        summary: str = "",
        metadata: Mapping[str, str] | None = None,
        available_at: datetime | None = None,
        max_attempts: int = 3,
        force_new: bool = False,
    ) -> object:
        """Queue a durable background learning job."""

    def upsert_step(self, step: Step) -> None:
        """Persist a Step."""

    def list_steps(self, *, loop_id: str | None = None) -> tuple[Step, ...]:
        """List Steps."""


@dataclass(frozen=True, slots=True)
class KernelDependencies:
    storage: KernelStoragePort
    context: ContextCapability
    recall: RecallCapability
    model_provider: ModelProviderCapability
    telemetry: TelemetrySinkCapability
    tools: ToolCapability | None = None
    delivery: DeliveryAdapterCapability | None = None
    embedding_service: EmbeddingService | None = None
    security_policy: SecurityPolicy | None = None
    skill_runtime: object | None = None
    # Optional hook for producer-side semantic indexing — episode summaries
    # and committed personal-model facts get pushed into the semantic index
    # on commit, so the NEXT turn's recall block can retrieve them with
    # BM25+vector fusion.
    semantic_summary_indexer: object | None = None


@dataclass(frozen=True, slots=True)
class KernelSourceRequest:
    route_id: str
    prompt: str
    surface: str = "kernel"
    source_event_type: str = "turn.received"
    source_payload: Mapping[str, Any] = field(default_factory=dict)
    source_event_id: str | None = None
    route_profile_id: str | None = None
    route_status: str = "open"
    route_interruption_state: str | None = None
    route_started_at: datetime | None = None
    request_id: str = field(default_factory=lambda: f"kernel-source-{uuid4().hex}")
    state_query: str | None = None
    tool_name: str | None = None
    tool_arguments: Mapping[str, Any] = field(default_factory=dict)
    delivery_payload: Mapping[str, Any] = field(default_factory=dict)
    owner_scope: str | None = None
    personal_model_id: str | None = None
    state_id: str | None = None
    episode_id: str | None = None
    loop_id: str | None = None
    episode_policy: str = "auto"
    episode_reuse_idle_seconds: int = 1800

    @property
    def source_id(self) -> str:
        return f"source:{self.request_id}"

    @property
    def event_id(self) -> str:
        return self.source_event_id or f"event:{self.request_id}"

    def to_event(self) -> EventEnvelope:
        payload = {
            "message": self.prompt,
            "content": self.prompt,
            "summary": self.prompt,
            **dict(self.source_payload),
            "source_id": self.source_id,
        }
        if self.owner_scope is not None:
            payload["owner_scope"] = self.owner_scope
        if self.personal_model_id is not None:
            payload["personal_model_id"] = self.personal_model_id
        if self.state_id is not None:
            payload["state_id"] = self.state_id
        if self.episode_id is not None:
            payload["episode_id"] = self.episode_id
        if self.loop_id is not None:
            payload["loop_id"] = self.loop_id
        if self.route_profile_id is not None:
            payload["profile_id"] = self.route_profile_id
        if self.route_interruption_state is not None:
            payload["interruption_state"] = self.route_interruption_state
        if self.route_status:
            payload["route_status"] = self.route_status
        return EventEnvelope(
            event_id=self.event_id,
            event_type=self.source_event_type,
            episode_id=self.route_id,
            source=self.surface,
            payload=payload,
        )

    @property
    def event(self) -> EventEnvelope:
        return self.to_event()

@dataclass(frozen=True, slots=True)
class KernelStageRecord:
    stage: str
    detail: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class KernelOutcome:
    event: EventEnvelope
    source_id: str
    personal_model: PersonalModel
    state: State
    episode: Episode
    loop: Loop
    steps: tuple[Step, ...]
    recall_items: tuple[RecallEvidence, ...]
    context: ContextBundle
    execution: ExecutionResult
    delivery: ExecutionResult | None
    stages: tuple[KernelStageRecord, ...]
    turn_messages: tuple[PromptMessage, ...] = ()

    @property
    def route_session_id(self) -> str:
        return self.event.episode_id

    @property
    def step_ids(self) -> tuple[str, ...]:
        return tuple(step.step_id for step in self.steps)

    def step_action_count(self, action: str, *, status: str | None = None) -> int:
        return sum(
            1
            for step in self.steps
            if step.action == action and (status is None or step.status == status)
        )

    @property
    def tool_call_count(self) -> int:
        return self.step_action_count("call_tool", status="completed")

    @property
    def model_turn_count(self) -> int:
        return self.step_action_count("call_model", status="completed")


@dataclass(frozen=True, slots=True)
class _TextToolCall:
    tool_name: str
    arguments: Mapping[str, Any]
    call_id: str = ""


@dataclass(frozen=True, slots=True)
class _ParsedToolCalls:
    cleaned_text: str
    calls: tuple[_TextToolCall, ...]


_MAX_PARALLEL_TOOL_WORKERS = 8
_NEVER_PARALLEL_TOOLS = frozenset({"tool.clarify"})
_PARALLEL_SAFE_TOOLS = frozenset(
    {
        "tool.file.read",
        "tool.file.search",
        "tool.personal_model.search",
        "tool.skill.list",
        "tool.skill.view",
        "tool.web.extract",
        "tool.web.read",
        "tool.web.search",
    }
)


@dataclass(frozen=True, slots=True)
class _ArtifactRequest:
    path: str


@dataclass(frozen=True, slots=True)
class _Clock:
    local_datetime: datetime
    timezone_name: str
    weekday: str
    local_date: str


@dataclass(frozen=True, slots=True)
class _RecallSelection:
    recall_items: tuple[RecallEvidence, ...]
    query: str
    work_item_ids: tuple[str, ...]
    scope_episode_ids: tuple[str, ...]
    scope_reason: str
    vector_cache_status: str = ""


_TOOL_CALL_WRAPPER_PATTERN = re.compile(r"</?(?:[\w.-]+:)?tool_call[^>]*>", re.IGNORECASE)
_INVOKE_PATTERN = re.compile(
    r"<(?:[\w.-]+:)?invoke\s+name=(?P<quote>[\"'])(?P<name>.+?)(?P=quote)\s*>(?P<body>.*?)</(?:[\w.-]+:)?invoke>",
    re.IGNORECASE | re.DOTALL,
)
_PARAMETER_PATTERN = re.compile(
    r"<(?:[\w.-]+:)?parameter\s+name=(?P<quote>[\"'])(?P<name>.+?)(?P=quote)\s*>(?P<value>.*?)</(?:[\w.-]+:)?parameter>",
    re.IGNORECASE | re.DOTALL,
)


def _parse_text_tool_calls(raw: str) -> _ParsedToolCalls:
    calls: list[_TextToolCall] = []
    for match in _INVOKE_PATTERN.finditer(raw):
        tool_name = match.group("name").strip()
        if not tool_name:
            continue
        arguments: dict[str, Any] = {}
        for parameter in _PARAMETER_PATTERN.finditer(match.group("body")):
            name = parameter.group("name").strip()
            if not name:
                continue
            arguments[name] = _decode_text_tool_argument(parameter.group("value"))
        calls.append(_TextToolCall(tool_name=tool_name, arguments=arguments))
    cleaned = _strip_tool_markup(raw)
    return _ParsedToolCalls(cleaned_text=cleaned, calls=tuple(calls))


def _parse_execution_tool_calls(result: ExecutionResult) -> _ParsedToolCalls:
    cleaned = _strip_tool_markup(result.summary)
    if result.tool_calls:
        calls = tuple(
            _TextToolCall(
                tool_name=str(call.tool_name).strip(),
                arguments={str(key): value for key, value in call.arguments.items()},
                call_id=str(call.call_id or "").strip(),
            )
            for call in result.tool_calls
            if str(call.tool_name).strip()
        )
        return _ParsedToolCalls(cleaned_text=cleaned, calls=calls)
    return _parse_text_tool_calls(result.summary)


_JSON_LITERAL_PATTERN = re.compile(
    r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$"
)
_ARTIFACT_PATH_PATTERNS = (
    re.compile(
        r"""(?ix)
        \b(?:save|saved|write|written)\b
        (?:(?:\s+[a-z][\w-]*){0,6})?
        \s+(?:to|as|into)\s+
        (?P<path>["'`]?[^"'`\s,;:]+["'`]?)
        """
    ),
    re.compile(
        r"""(?ix)
        \b(?:file|markdown\s+file|report\s+file|notes\s+file)\b
        (?:(?:\s+[a-z][\w-]*){0,4})?
        \s+(?:named\s+)?
        (?P<path>["'`]?[^"'`\s,;:]+["'`]?)
        """
    ),
)


def _decode_text_tool_argument(raw_value: str) -> object:
    candidate = html_unescape(raw_value).strip()
    if not candidate:
        return ""
    if (
        candidate[0] in "[{\""
        or candidate in {"true", "false", "null"}
        or _JSON_LITERAL_PATTERN.match(candidate)
    ):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return candidate
    return candidate


def _strip_tool_markup(raw: str) -> str:
    cleaned = _INVOKE_PATTERN.sub("", raw)
    cleaned = _TOOL_CALL_WRAPPER_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _clean_execution_summary(result: ExecutionResult) -> ExecutionResult:
    cleaned = _dedupe_adjacent_repetition(_strip_tool_markup(result.summary))
    if not cleaned or cleaned == result.summary:
        return result
    return replace(result, summary=cleaned)


def _dedupe_adjacent_repetition(raw: str) -> str:
    text = raw.strip()
    if len(text) < 24:
        return text
    for separator in ("\n\n", "\n", " "):
        parts = [part.strip() for part in text.split(separator)]
        if len(parts) >= 2 and len(parts) % 2 == 0:
            midpoint = len(parts) // 2
            if parts[:midpoint] == parts[midpoint:] and any(part for part in parts[:midpoint]):
                return separator.join(parts[:midpoint]).strip()
    if len(text) % 2 == 0:
        midpoint = len(text) // 2
        left = text[:midpoint].strip()
        right = text[midpoint:].strip()
        if left and left == right:
            return left
    return text


def _with_execution_usage(
    result: ExecutionResult,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cached_prompt_tokens: int = 0,
    cache_creation_prompt_tokens: int = 0,
    cache_usage_reported: bool = False,
) -> ExecutionResult:
    return replace(
        result,
        prompt_tokens=max(0, prompt_tokens),
        completion_tokens=max(0, completion_tokens),
        total_tokens=max(0, total_tokens),
        cached_prompt_tokens=max(0, cached_prompt_tokens),
        cache_creation_prompt_tokens=max(0, cache_creation_prompt_tokens),
        cache_usage_reported=cache_usage_reported,
    )


def _execute_direct_tool_loop(
    *,
    request: KernelSourceRequest,
    session: Episode,
    tool_capability: ToolCapability,
    persist_loop_checkpoint: Any,
) -> tuple[ExecutionResult, LoopState]:
    loop_service = LoopCheckpointService()
    checkpoint = loop_service.start_loop(
        episode_id=session.episode_id,
        source_event_id=request.event.event_id,
        prompt=request.prompt,
    )
    persist_loop_checkpoint(checkpoint)
    result = tool_capability.invoke(
        request.tool_name or "",
        dict(request.tool_arguments),
        session_id=session.episode_id,
    )
    checkpoint, tool_step = loop_service.record_tool_step(
        checkpoint,
        tool_name=request.tool_name or "",
        arguments=request.tool_arguments,
        result=result,
    )
    persist_loop_checkpoint(checkpoint, step=tool_step)
    checkpoint = loop_service.complete(checkpoint, summary=result.summary)
    persist_loop_checkpoint(checkpoint)
    return result, checkpoint


def _role_preserved_tool_interaction_messages(
    *,
    assistant_summary: str,
    calls: tuple[_TextToolCall, ...],
    observations: tuple[str, ...],
) -> tuple[PromptMessage, ...]:
    tool_calls = tuple(
        {
            "id": _tool_call_id(index=index, call=call),
            "name": call.tool_name,
            "arguments": dict(call.arguments),
        }
        for index, call in enumerate(calls, start=1)
    )
    messages: list[PromptMessage] = [
        PromptMessage(
            role="assistant",
            content=_strip_tool_markup(assistant_summary).strip(),
            tool_calls=tool_calls,
        )
    ]
    for index, (call, observation) in enumerate(zip(calls, observations, strict=False), start=1):
        messages.append(
            PromptMessage(
                role="tool",
                content=observation,
                tool_call_id=_tool_call_id(index=index, call=call),
                tool_name=call.tool_name,
            )
        )
    return tuple(messages)


def _tool_call_id(*, index: int, call: _TextToolCall) -> str:
    if call.call_id:
        return call.call_id
    digest = hashlib.sha1(_tool_call_signature(call).encode("utf-8")).hexdigest()[:10]
    return f"call_{index}_{digest}"


def _format_tool_arguments(arguments: Mapping[str, Any]) -> str:
    if not arguments:
        return "<none>"
    return ", ".join(f"{key}={_render_tool_argument_value(value)}" for key, value in sorted(arguments.items()))


def _tool_call_signature(call: _TextToolCall) -> str:
    payload = json.dumps(dict(sorted(call.arguments.items())), separators=(",", ":"), sort_keys=True)
    return f"{call.tool_name}:{payload}"


def _deduplicate_tool_calls(calls: Iterable[_TextToolCall]) -> tuple[_TextToolCall, ...]:
    unique: list[_TextToolCall] = []
    seen: set[str] = set()
    for call in calls:
        signature = _tool_call_signature(call)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(call)
    return tuple(unique)


def _should_parallelize_tool_batch(calls: tuple[_TextToolCall, ...]) -> bool:
    if len(calls) <= 1:
        return False
    for call in calls:
        if call.tool_name in _NEVER_PARALLEL_TOOLS:
            return False
        if call.tool_name == "tool.sub_agents":
            if not _sub_agents_call_is_parallel_safe(call):
                return False
            continue
        if call.tool_name not in _PARALLEL_SAFE_TOOLS:
            return False
        if (
            call.tool_name == "tool.file.read"
            and _normalized_tool_path(call.arguments.get("path")) is None
        ):
            return False
    return True


def _sub_agents_call_is_parallel_safe(call: _TextToolCall) -> bool:
    action = str(call.arguments.get("action") or "run").strip().lower()
    return action in {"start", "status", "check", "list"}


def _normalized_tool_path(raw_path: object) -> Path | None:
    if not isinstance(raw_path, (str, os.PathLike)):
        return None
    candidate = os.fspath(raw_path).strip()
    if not candidate:
        return None
    try:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _render_tool_argument_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _model_turn_summary(result: ExecutionResult, *, parsed: _ParsedToolCalls) -> str:
    if parsed.cleaned_text.strip():
        return parsed.cleaned_text.strip()
    if parsed.calls:
        tool_list = ", ".join(call.tool_name for call in parsed.calls)
        return f"requested tool work: {tool_list}"
    return result.summary.strip()


def _resolve_clock_timezone(timezone_name: str | None) -> tuple[timezone | ZoneInfo, str]:
    candidate = str(timezone_name or os.environ.get("ELEPHANT_TIMEZONE") or os.environ.get("TZ") or "").strip()
    if candidate:
        try:
            return ZoneInfo(candidate), candidate
        except ZoneInfoNotFoundError:
            pass
    local_now = datetime.now().astimezone()
    local_tzinfo = local_now.tzinfo
    if local_tzinfo is not None:
        return local_tzinfo, local_now.tzname() or "local"
    return timezone.utc, "UTC"


def _build_clock(user_timezone: str | None = None, *, now: datetime | None = None) -> _Clock:
    resolved_now = now or _utc_now()
    if resolved_now.tzinfo is None:
        resolved_now = resolved_now.replace(tzinfo=timezone.utc)
    tzinfo, timezone_name = _resolve_clock_timezone(user_timezone)
    local = resolved_now.astimezone(tzinfo)
    # Prefer short tzname (e.g. "CST") over zone key (e.g. "Asia/Shanghai")
    short_name = local.tzname()
    if short_name and len(short_name) <= 5:
        timezone_name = short_name
    return _Clock(
        local_datetime=local,
        timezone_name=timezone_name,
        weekday=local.strftime("%A"),
        local_date=local.date().isoformat(),
    )


def _time_annotation(clock: _Clock) -> str:
    return f"[Time: {clock.local_date} {clock.local_datetime.strftime('%H:%M')} {clock.timezone_name}, {clock.weekday}]"


def _has_temporal_keywords(normalized_prompt: str) -> bool:
    temporal_markers = (
        "latest",
        "recent",
        "today",
        "newest",
        "up-to-date",
        "this week",
        "this month",
        "this year",
        "tomorrow",
        "yesterday",
        "今天",
        "今日",
        "明天",
        "昨天",
        "当前",
        "现在",
        "最新",
        "近期",
        "最近",
        "本周",
        "本月",
        "今年",
        "刚刚",
        "刚发布",
    )
    return any(marker in normalized_prompt for marker in temporal_markers)


def _should_inject_time(
    prompt: str,
    *,
    is_first_turn: bool,
    session_updated_at: datetime | None,
    now: datetime,
) -> bool:
    """Inject time if: first turn, idle > 1h, or temporal keywords in prompt."""
    if is_first_turn:
        return True
    if session_updated_at is not None:
        idle_seconds = (now - session_updated_at).total_seconds()
        if idle_seconds > 3600:
            return True
    normalized = " ".join(prompt.casefold().split())
    return _has_temporal_keywords(normalized)


def _has_temporal_request_markers(normalized_prompt: str) -> bool:
    temporal_markers = (
        "latest",
        "recent",
        "current",
        "today",
        "newest",
        "up-to-date",
        "this week",
        "this month",
        "this year",
        "今天",
        "今日",
        "当前",
        "现在",
        "最新",
        "近期",
        "最近",
        "本周",
        "本月",
        "今年",
        "刚刚",
        "刚发布",
    )
    return any(marker in normalized_prompt for marker in temporal_markers)


def _has_compare_request_markers(normalized_prompt: str) -> bool:
    return any(marker in normalized_prompt for marker in ("compare", "comparison", "versus", " vs ", "对比", "比较"))


def _apply_execution_guidance(prompt: str) -> str:
    """Append execution strategy hints (multi-source, compare, artifact). No time info."""
    if "Execution guidance for this turn:" in prompt:
        return prompt
    normalized = " ".join(prompt.casefold().split())
    if not normalized:
        return prompt
    multi_source = _looks_like_multi_source_research_request(normalized)
    artifact_request = _artifact_request_from_prompt(prompt)
    compare_request = _has_compare_request_markers(normalized)
    if not (multi_source or artifact_request is not None or compare_request):
        return prompt
    lines = ["Execution guidance for this turn:"]
    if multi_source:
        lines.append("- Use more than one tool step and at least two distinct sources before concluding.")
        lines.append("- Preferred flow: tool.web.search first, then tool.web.extract or multiple tool.web.read calls, then synthesize.")
    if compare_request:
        lines.append("- Compare approaches explicitly instead of returning a single-source note.")
    if artifact_request is not None:
        lines.append(
            f"- The user explicitly requested a saved artifact at {artifact_request.path}; complete the work and persist it there with tool.file.write or tool.code.execute."
        )
    return f"{prompt.rstrip()}\n\n" + "\n".join(lines)


def _looks_like_multi_source_research_request(normalized_prompt: str) -> bool:
    research_markers = (
        "research",
        "latest",
        "recent",
        "current",
        "approach",
        "approaches",
        "compare",
        "comparison",
        "ablation",
        "survey",
        "investigate",
    )
    synthesis_markers = ("summary", "summarize", "write a summary", "report", "overview")
    return any(marker in normalized_prompt for marker in research_markers) and (
        any(marker in normalized_prompt for marker in synthesis_markers)
        or any(marker in normalized_prompt for marker in ("compare", "comparison", "latest"))
    )


def _artifact_request_from_prompt(prompt: str) -> _ArtifactRequest | None:
    for pattern in _ARTIFACT_PATH_PATTERNS:
        match = pattern.search(prompt)
        if match is None:
            continue
        candidate = _normalize_artifact_path_candidate(match.group("path"))
        if candidate is None:
            continue
        return _ArtifactRequest(path=candidate)
    return None


def _normalize_artifact_path_candidate(raw_value: str) -> str | None:
    candidate = raw_value.strip().strip("\"'`").rstrip(".,;:)]}")
    if not candidate or "://" in candidate:
        return None
    if "/" not in candidate and "." not in candidate:
        return None
    if "." not in Path(candidate).name:
        return None
    if candidate.startswith("-"):
        return None
    return candidate


def _tool_result_preview(summary: str, *, preview_chars: int) -> str:
    normalized = summary.strip()
    if preview_chars <= 0:
        return normalized
    if len(normalized) <= preview_chars:
        return normalized
    return f"{normalized[: max(0, preview_chars - 15)].rstrip()} ... [truncated]"


def _tool_result_budget_config(
    *,
    preview_chars: int,
    turn_budget_chars: int,
    persist_threshold_chars: int,
) -> ToolResultBudgetConfig:
    return ToolResultBudgetConfig(
        result_size_chars=persist_threshold_chars,
        turn_budget_chars=turn_budget_chars,
        preview_size_chars=preview_chars,
    )


def _budget_tool_result_summary(
    summary: str,
    *,
    tool_name: str,
    tool_use_id: str,
    config: ToolResultBudgetConfig,
) -> str:
    return maybe_persist_tool_result(
        summary,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        config=config,
    )


def _enforce_observation_budget(
    observations: list[str],
    *,
    turn_budget_chars: int | None = None,
    config: ToolResultBudgetConfig | None = None,
) -> list[str]:
    if config is None:
        config = ToolResultBudgetConfig(turn_budget_chars=turn_budget_chars or 0)
    return enforce_tool_observation_budget(observations, config=config)


__all__ = [name for name in globals() if not name.startswith("__")]
