"""Runtime-owned reconciliation signal helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Protocol
from uuid import uuid4

from packages.contracts.runtime import (
    EventEnvelope,
    ExecutionResult,
    PromptMessage,
)


class _EventAppender(Protocol):
    def append_event(self, event: EventEnvelope):
        """Append a durable event envelope."""


def merge_preference_updates(existing: tuple[str, ...], updates: tuple[str, ...]) -> tuple[str, ...]:
    """Merge extracted preference updates into the durable profile preference tuple."""

    merged = [value.strip() for value in existing if value.strip()]
    for update in updates:
        normalized = update.strip()
        if not normalized:
            continue
        prefix = _preference_prefix(normalized)
        if prefix is not None:
            merged = [value for value in merged if not value.startswith(prefix)]
        if normalized not in merged:
            merged.append(normalized)
    return tuple(merged)


@dataclass(frozen=True, slots=True)
class WakeSignal:
    session_id: str
    source: str
    durable_events: tuple[EventEnvelope, ...]
    decision_summary: str
    observed_delta: bool
    summary: str


@dataclass(frozen=True, slots=True)
class WakeReconciliationReport:
    source: str
    observed_delta: bool
    appended_event_types: tuple[str, ...]
    summary: str
    ignored_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TurnProfileDelta:
    user_fields: tuple[tuple[str, str], ...] = ()
    preference_updates: tuple[str, ...] = ()
    relationship_notes: tuple[str, ...] = ()
    summary: str = ""

    @property
    def observed(self) -> bool:
        return bool(self.user_fields or self.preference_updates or self.relationship_notes)


@dataclass(frozen=True, slots=True)
class TurnSignal:
    session_id: str
    source: str
    inbound_event: EventEnvelope
    durable_events: tuple[EventEnvelope, ...]
    profile_delta: TurnProfileDelta
    decision_summary: str
    observed_state_delta: bool
    summary: str


@dataclass(frozen=True, slots=True)
class TurnReconciliationReport:
    source: str
    observed_state_delta: bool
    observed_profile_delta: bool
    appended_event_types: tuple[str, ...]
    summary: str = ""
    ignored_reason: str | None = None


class ReconciliationPipeline:
    """Build durable reconciliation signals from runtime execution."""

    def observe_wake(
        self,
        *,
        session_id: str,
        durable_events: tuple[EventEnvelope, ...],
        decision_summary: str,
        observed_delta: bool = False,
        source: str = "cli.wake",
    ) -> WakeSignal:
        summary = (
            "Observed a wake-owned State continuity delta."
            if observed_delta
            else "Observed wake rationale without a durable elephant delta."
        )
        return WakeSignal(
            session_id=session_id,
            source=source,
            durable_events=durable_events,
            decision_summary=decision_summary,
            observed_delta=observed_delta,
            summary=summary,
        )

    def observe_turn(
        self,
        *,
        inbound_event: EventEnvelope,
        execution: ExecutionResult,
        decision_summary: str | None = None,
        include_input_event: bool = True,
        include_outcome_event: bool = True,
        source: str | None = None,
        profile_id: str | None = None,
        elephant_id: str | None = None,
        turn_messages: tuple[PromptMessage, ...] = (),
        observed_state_delta: bool = False,
    ) -> TurnSignal:
        resolved_source = source or inbound_event.source
        prompt_text = _event_text(inbound_event)
        profile_delta = _extract_turn_profile_delta(prompt_text)
        durable_events: list[EventEnvelope] = []
        if include_input_event:
            durable_events.append(inbound_event)
        if include_outcome_event:
            outcome_event = _turn_outcome_event(
                session_id=inbound_event.episode_id,
                source=resolved_source,
                inbound_event=inbound_event,
                execution=execution,
                decision_summary=decision_summary,
            )
            if outcome_event is not None:
                durable_events.append(outcome_event)
        del profile_id, elephant_id, turn_messages
        observed_parts: list[str] = []
        if observed_state_delta:
            observed_parts.append("a durable elephant delta")
        if profile_delta.observed:
            observed_parts.append(profile_delta.summary or "profile and relationship deltas")
        if not observed_parts:
            observed_parts.append("no durable owner delta beyond Step records")
        summary = "Observed a turn-owned reconciliation candidate with " + ", ".join(observed_parts) + "."
        return TurnSignal(
            session_id=inbound_event.episode_id,
            source=resolved_source,
            inbound_event=inbound_event,
            durable_events=tuple(durable_events),
            profile_delta=profile_delta,
            decision_summary=(decision_summary or execution.summary).strip(),
            observed_state_delta=observed_state_delta,
            summary=summary,
        )


class StateReconciler:
    """Apply runtime reconciliation signals to durable owners."""

    def reconcile_wake(
        self,
        *,
        repository,
        recall_runtime: _EventAppender,
        observation: WakeSignal,
        inspect_only: bool = False,
    ) -> WakeReconciliationReport:
        if inspect_only:
            return WakeReconciliationReport(
                source=observation.source,
                observed_delta=observation.observed_delta,
                appended_event_types=(),
                summary="Ignored the wake-owned durable delta because inspect-only mode requested no writes.",
                ignored_reason="inspect_only",
            )

        appended_event_types: list[str] = []
        for event in observation.durable_events:
            recall_runtime.append_event(event)
            appended_event_types.append(event.event_type)

        return WakeReconciliationReport(
            source=observation.source,
            observed_delta=observation.observed_delta,
            appended_event_types=tuple(appended_event_types),
            summary="Recorded wake rationale events through runtime reconciliation.",
        )

    def reconcile_turn(
        self,
        *,
        repository,
        recall_runtime: _EventAppender,
        observation: TurnSignal,
        inspect_only: bool = False,
    ) -> TurnReconciliationReport:
        if inspect_only:
            return TurnReconciliationReport(
                source=observation.source,
                observed_state_delta=observation.observed_state_delta,
                observed_profile_delta=observation.profile_delta.observed,
                appended_event_types=(),
                summary="Ignored the turn-owned durable delta because inspect-only mode requested no writes.",
                ignored_reason="inspect_only",
            )

        appended_event_types: list[str] = []
        for event in observation.durable_events:
            recall_runtime.append_event(event)
            appended_event_types.append(event.event_type)

        summary_parts: list[str] = []
        if observation.observed_state_delta:
            summary_parts.append("observed a elephant delta")
        else:
            summary_parts.append("kept State reconciliation signal-only")
        if appended_event_types:
            summary_parts.append(f"recorded {len(appended_event_types)} durable events")
        if observation.profile_delta.observed:
            summary_parts.append("extracted profile and relationship deltas for the calling surface")
        summary = "Turn reconciliation " + ", ".join(summary_parts) + "."

        return TurnReconciliationReport(
            source=observation.source,
            observed_state_delta=observation.observed_state_delta,
            observed_profile_delta=observation.profile_delta.observed,
            appended_event_types=tuple(appended_event_types),
            summary=summary,
        )


def _extract_turn_profile_delta(text: str) -> TurnProfileDelta:
    normalized = text.strip()
    if not normalized:
        return TurnProfileDelta(summary="")
    user_fields = tuple(_extract_user_fields(normalized).items())
    preference_updates = _extract_preference_updates(normalized)
    relationship_notes = _extract_relationship_notes(normalized)
    summary_parts: list[str] = []
    if user_fields:
        summary_parts.append("user profile fields")
    if preference_updates:
        summary_parts.append("communication preferences")
    if relationship_notes:
        summary_parts.append("relationship continuity notes")
    return TurnProfileDelta(
        user_fields=user_fields,
        preference_updates=preference_updates,
        relationship_notes=relationship_notes,
        summary=", ".join(summary_parts),
    )


def _extract_user_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    preferred = _first_match(
        text,
        (
            r"(?im)^\s*(?:preferred name|name|nickname)\s*[:：]\s*(.+)$",
            r"(?im)^\s*(?:称呼|叫我)\s*[:：]\s*(.+)$",
            r"(?i)\b(?:call me|i go by|my name is|i'm called|i am called)\s+([^\n,.;:]+)",
            r"(?i)(?:可以叫我|叫我|我叫)\s*([^\n，。；：,.;:]+)",
        ),
    )
    if preferred is not None:
        fields["preferred_name"] = preferred
    current_work = _first_match(
        text,
        (
            r"(?im)^\s*(?:current work|work|work focus)\s*[:：]\s*(.+)$",
            r"(?im)^\s*(?:当前工作|工作方向|目前在做)\s*[:：]\s*(.+)$",
            r"(?i)\b(?:i work on|i'm working on|i am working on|i build|i'm building|i am building|current work is|my work is)\s+([^\n.!?]+)",
            r"(?i)(?:我在做|我目前在做|我正在做|我在研究|我正在研究)\s*([^\n。！？]+)",
        ),
    )
    if current_work is not None:
        fields["current_work"] = current_work
    return fields


def _extract_preference_updates(text: str) -> tuple[str, ...]:
    updates: list[str] = []
    lower = text.lower()
    if re.search(
        r"(?i)(?:reply|respond|responses|replies|answers|be|keep).{0,24}(?:concise|brief|short)",
        text,
    ) or any(token in text for token in ("简洁", "简短", "精炼")):
        updates.append("verbosity:concise")
    if re.search(
        r"(?i)(?:reply|respond|responses|replies|answers|be|keep).{0,24}(?:detailed|thorough|long-form)",
        text,
    ) or any(token in text for token in ("详细", "展开一些")):
        updates.append("verbosity:detailed")
    if re.search(r"(?i)(?:reply|respond).{0,16}(?:in chinese)", text) or any(
        token in text for token in ("用中文", "中文回答", "请中文回答")
    ):
        updates.append("language:zh-CN")
    if re.search(r"(?i)(?:reply|respond).{0,16}(?:in english)", text) or any(
        token in text for token in ("用英文", "英文回答", "请英文回答")
    ):
        updates.append("language:en")
    if "bullet" in lower or "bullets" in lower or "bullet points" in lower or "要点" in text or "列表" in text:
        updates.append("response-style:bullets")
    return tuple(dict.fromkeys(updates))


def _extract_relationship_notes(text: str) -> tuple[str, ...]:
    notes: list[str] = []
    lines = [line.strip() for line in re.split(r"[\n\r]+", text) if line.strip()]
    if not lines and text.strip():
        lines = [text.strip()]
    for line in lines:
        lowered = line.lower()
        if (
            _first_match(
                line,
                (
                    r"(?im)^\s*(?:preferred name|name|nickname|current work|work|work focus)\s*[:：]",
                    r"(?im)^\s*(?:称呼|叫我|当前工作|工作方向|目前在做)\s*[:：]",
                ),
            )
            is not None
        ):
            continue
        if any(
            marker in lowered
            for marker in (
                "keep replies",
                "keep response",
                "keep responses",
                "reply to me",
                "talk to me",
                "remember that",
                "for future reference",
                "don't call me",
                "do not call me",
                "keep it",
            )
        ) or any(
            marker in line
            for marker in (
                "以后",
                "记住",
                "下次",
                "别叫我",
                "不要叫我",
                "回复时",
                "回答时",
                "说话时",
            )
        ):
            cleaned = _clean_capture(line)
            if cleaned:
                notes.append(cleaned)
    return tuple(dict.fromkeys(notes))


def _turn_outcome_event(
    *,
    session_id: str,
    source: str,
    inbound_event: EventEnvelope,
    execution: ExecutionResult,
    decision_summary: str | None,
) -> EventEnvelope | None:
    content_parts: list[str] = []
    rationale = (decision_summary or "").strip()
    if rationale:
        content_parts.append(rationale)
    summary = execution.summary.strip()
    if summary and summary not in content_parts:
        content_parts.append(summary)
    content = "\n".join(part for part in content_parts if part)
    if not content:
        return None
    return EventEnvelope(
        event_id=f"event:{uuid4().hex}",
        event_type="decision",
        episode_id=session_id,
        source=source,
        payload={
            "content": content,
            "summary": content.splitlines()[0],
            "signal_kind": "decision",
            "tags": "continuity,assistant,turn-outcome",
            "source_event_id": inbound_event.event_id,
            "execution_id": execution.execution_id,
            "execution_outcome": execution.outcome,
        },
    )


def _transcript_user_message(messages: tuple[PromptMessage, ...]) -> str:
    for message in messages:
        if message.role == "user" and message.content.strip():
            return message.content.strip()
    return ""


def _transcript_final_assistant_response(messages: tuple[PromptMessage, ...]) -> str:
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        if message.tool_calls:
            continue
        content = message.content.strip()
        if content:
            return content
    return ""


def _transcript_tool_result_details(
    messages: tuple[PromptMessage, ...],
) -> tuple[str, ...]:
    details: list[str] = []
    for message in messages:
        if message.role != "tool":
            continue
        label = message.tool_name.strip() or message.tool_call_id.strip() or "tool"
        content = _compact_text(message.content, limit=360)
        if content:
            details.append(f"tool_result:{label}:{content}")
        else:
            details.append(f"tool_result:{label}:empty")
    return tuple(dict.fromkeys(details))


def _transcript_action_details(messages: tuple[PromptMessage, ...]) -> tuple[str, ...]:
    details: list[str] = []
    for message in messages:
        if message.role != "assistant":
            continue
        for call in message.tool_calls:
            name = _tool_call_name_from_mapping(call)
            call_id = str(call.get("id") or call.get("call_id") or "").strip()
            argument_keys = _tool_call_argument_keys(call)
            suffix = f" args={','.join(argument_keys)}" if argument_keys else ""
            if call_id:
                suffix = f"{suffix} id={call_id}"
            details.append(f"tool_call:{name or 'tool'}{suffix}")
        content = message.content.strip()
        if content and not message.tool_calls:
            details.append(f"assistant_response:{_compact_text(content, limit=360)}")
    return tuple(dict.fromkeys(details))


def _tool_call_name_from_mapping(call: Mapping[str, object]) -> str:
    direct = str(call.get("name") or call.get("tool_name") or "").strip()
    if direct:
        return direct
    function = call.get("function")
    if isinstance(function, Mapping):
        return str(function.get("name") or "").strip()
    return ""


def _tool_call_argument_keys(call: Mapping[str, object]) -> tuple[str, ...]:
    arguments = call.get("arguments")
    if isinstance(arguments, Mapping):
        return tuple(sorted(str(key) for key in arguments.keys()))
    function = call.get("function")
    if isinstance(function, Mapping):
        function_arguments = function.get("arguments")
        if isinstance(function_arguments, Mapping):
            return tuple(sorted(str(key) for key in function_arguments.keys()))
    return ()


def _tool_call_details(execution: ExecutionResult) -> tuple[str, ...]:
    details: list[str] = []
    for call in execution.tool_calls:
        argument_keys = tuple(sorted(str(key) for key in call.arguments.keys()))
        if argument_keys:
            details.append(f"{call.tool_name}({', '.join(argument_keys)})")
        else:
            details.append(call.tool_name)
    for artifact_id in execution.produced_artifact_ids:
        resolved = artifact_id.strip()
        if resolved:
            details.append(f"artifact:{resolved}")
    return tuple(dict.fromkeys(details))


def _payload_text(event: EventEnvelope, *keys: str) -> str:
    for key in keys:
        value = event.payload.get(key)
        if value is None:
            continue
        cleaned = str(value).strip()
        if cleaned:
            return cleaned
    return ""


def _compact_text(value: str, *, limit: int) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "..."


def _event_text(event: EventEnvelope) -> str:
    payload = event.payload
    text = payload.get("content") or payload.get("message") or payload.get("summary") or ""
    return str(text).strip()


def _first_match(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match is not None:
            value = match.group(1).strip()
            if value:
                return _clean_capture(value)
    return None


def _clean_capture(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n\"'“”‘’")
    return cleaned.rstrip(".。;；")


def _preference_prefix(value: str) -> str | None:
    if ":" not in value:
        return None
    return value.split(":", 1)[0].strip() + ":"
