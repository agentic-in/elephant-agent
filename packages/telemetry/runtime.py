"""Backend-neutral telemetry contracts and helper APIs.

Telemetry must stay observational. The rest of the runtime can depend on these
typed records and helper functions without knowing which sink, collector, or
hosted backend receives the events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import (
    Any,
    Callable,
    ClassVar,
    Literal,
    Mapping,
    Protocol,
    runtime_checkable,
)

TelemetryFamily = Literal["lifecycle", "execution", "approval", "delivery", "failure"]
TelemetryPhase = Literal["ingest", "resolve", "recover", "assemble", "select", "execute", "persist", "emit"]
LifecycleStatus = Literal["started", "completed", "skipped"]
ExecutionStatus = Literal["started", "completed", "blocked", "failed"]
ApprovalDecision = Literal["approved", "denied", "deferred"]
DeliveryStatus = Literal["queued", "sent", "acknowledged", "failed"]
FailureSeverity = Literal["debug", "info", "warning", "error", "critical"]
TelemetryEmitter = Callable[[Mapping[str, Any]], None]

LIFECYCLE_FAMILY: TelemetryFamily = "lifecycle"
EXECUTION_FAMILY: TelemetryFamily = "execution"
APPROVAL_FAMILY: TelemetryFamily = "approval"
DELIVERY_FAMILY: TelemetryFamily = "delivery"
FAILURE_FAMILY: TelemetryFamily = "failure"

LIFECYCLE_PHASES: tuple[TelemetryPhase, ...] = (
    "ingest",
    "resolve",
    "recover",
    "assemble",
    "select",
    "execute",
    "persist",
    "emit",
)

EXECUTION_STATUSES: tuple[ExecutionStatus, ...] = (
    "started",
    "completed",
    "blocked",
    "failed",
)
APPROVAL_DECISIONS: tuple[ApprovalDecision, ...] = ("approved", "denied", "deferred")
DELIVERY_STATUSES: tuple[DeliveryStatus, ...] = (
    "queued",
    "sent",
    "acknowledged",
    "failed",
)
FAILURE_SEVERITIES: tuple[FailureSeverity, ...] = (
    "debug",
    "info",
    "warning",
    "error",
    "critical",
)

KRN_REQUIRED_EVENTS = (
    "lifecycle.turn.ingested",
    "lifecycle.episode.resolved",
    "lifecycle.state.recovered",
    "lifecycle.context.assembled",
    "execution.move.selected",
    "execution.tool.requested",
    "execution.reply.emitted",
    "lifecycle.outcomes.persisted",
    "delivery.surface.emitted",
    "failure.runtime.reported",
)

SEC_REQUIRED_EVENTS = (
    "approval.requested",
    "approval.classified",
    "approval.decided",
    "approval.granted",
    "approval.denied",
)

OPS_REQUIRED_EVENTS = (
    "approval.requested",
    "approval.decided",
    "execution.side_effect.started",
    "execution.side_effect.completed",
    "delivery.audit.recorded",
    "failure.side_effect.reported",
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _record(event: object) -> dict[str, Any]:
    if hasattr(event, "to_record"):
        return dict(getattr(event, "to_record")())
    if isinstance(event, Mapping):
        return dict(event)
    raise TypeError("telemetry event must expose to_record() or be a mapping")


def _emit(sink: TelemetryEmitter | object, event: Mapping[str, Any]) -> Mapping[str, Any]:
    if callable(sink):
        sink(event)
        return event
    emit = getattr(sink, "emit", None)
    if emit is None:
        raise TypeError("telemetry sink must be callable or expose emit()")
    emit(event)
    return event


@runtime_checkable
class TelemetrySink(Protocol):
    def emit(self, event: Mapping[str, Any]) -> None:
        """Emit a backend-neutral telemetry event record."""


@dataclass(frozen=True, slots=True)
class TelemetryMetadata:
    event_id: str
    episode_id: str | None = None
    source: str = "unknown"
    occurred_at: datetime = field(default_factory=_utc_now)
    trace_id: str | None = None
    span_id: str | None = None
    parent_event_id: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "episode_id": self.episode_id,
            "source": self.source,
            "occurred_at": self.occurred_at.isoformat(),
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_event_id": self.parent_event_id,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True, slots=True)
class LifecycleTelemetryEvent:
    metadata: TelemetryMetadata
    name: str
    phase: TelemetryPhase
    status: LifecycleStatus
    subject_id: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    family: ClassVar[TelemetryFamily] = LIFECYCLE_FAMILY

    def to_record(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "name": self.name,
            "phase": self.phase,
            "status": self.status,
            "subject_id": self.subject_id,
            "detail": dict(self.detail),
            **self.metadata.to_record(),
        }


@dataclass(frozen=True, slots=True)
class ExecutionTelemetryEvent:
    metadata: TelemetryMetadata
    name: str
    operation: str
    status: ExecutionStatus
    target: str | None = None
    resource_id: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    family: ClassVar[TelemetryFamily] = EXECUTION_FAMILY

    def to_record(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "name": self.name,
            "operation": self.operation,
            "status": self.status,
            "target": self.target,
            "resource_id": self.resource_id,
            "detail": dict(self.detail),
            **self.metadata.to_record(),
        }


@dataclass(frozen=True, slots=True)
class ApprovalTelemetryEvent:
    metadata: TelemetryMetadata
    name: str
    decision: ApprovalDecision
    policy_id: str
    risk_class: str
    request_kind: str
    reason: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    family: ClassVar[TelemetryFamily] = APPROVAL_FAMILY

    def to_record(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "name": self.name,
            "decision": self.decision,
            "policy_id": self.policy_id,
            "risk_class": self.risk_class,
            "request_kind": self.request_kind,
            "reason": self.reason,
            "detail": dict(self.detail),
            **self.metadata.to_record(),
        }


@dataclass(frozen=True, slots=True)
class DeliveryTelemetryEvent:
    metadata: TelemetryMetadata
    name: str
    channel: str
    status: DeliveryStatus
    destination: str | None = None
    payload_kind: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    family: ClassVar[TelemetryFamily] = DELIVERY_FAMILY

    def to_record(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "name": self.name,
            "channel": self.channel,
            "status": self.status,
            "destination": self.destination,
            "payload_kind": self.payload_kind,
            "detail": dict(self.detail),
            **self.metadata.to_record(),
        }


@dataclass(frozen=True, slots=True)
class FailureTelemetryEvent:
    metadata: TelemetryMetadata
    name: str
    error_kind: str
    severity: FailureSeverity
    recoverable: bool
    status: Literal["failed"] = "failed"
    operation: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    family: ClassVar[TelemetryFamily] = FAILURE_FAMILY

    def to_record(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "name": self.name,
            "error_kind": self.error_kind,
            "severity": self.severity,
            "recoverable": self.recoverable,
            "status": self.status,
            "operation": self.operation,
            "detail": dict(self.detail),
            **self.metadata.to_record(),
        }


def emit_event(sink: TelemetryEmitter | TelemetrySink, event: object) -> dict[str, Any]:
    """Normalize and emit a telemetry event through any backend-neutral sink."""

    record = _record(event)
    _emit(sink, record)
    return record


def emit_lifecycle_event(
    sink: TelemetryEmitter | TelemetrySink,
    *,
    event_id: str,
    name: str,
    phase: TelemetryPhase,
    status: LifecycleStatus,
    episode_id: str | None = None,
    source: str = "unknown",
    subject_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_event_id: str | None = None,
    attributes: Mapping[str, Any] | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event = LifecycleTelemetryEvent(
        metadata=TelemetryMetadata(
            event_id=event_id,
            episode_id=episode_id,
            source=source,
            trace_id=trace_id,
            span_id=span_id,
            parent_event_id=parent_event_id,
            attributes={} if attributes is None else dict(attributes),
        ),
        name=name,
        phase=phase,
        status=status,
        subject_id=subject_id,
        detail={} if detail is None else dict(detail),
    )
    return emit_event(sink, event)


def emit_execution_event(
    sink: TelemetryEmitter | TelemetrySink,
    *,
    event_id: str,
    name: str,
    operation: str,
    status: ExecutionStatus,
    episode_id: str | None = None,
    source: str = "unknown",
    target: str | None = None,
    resource_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_event_id: str | None = None,
    attributes: Mapping[str, Any] | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event = ExecutionTelemetryEvent(
        metadata=TelemetryMetadata(
            event_id=event_id,
            episode_id=episode_id,
            source=source,
            trace_id=trace_id,
            span_id=span_id,
            parent_event_id=parent_event_id,
            attributes={} if attributes is None else dict(attributes),
        ),
        name=name,
        operation=operation,
        status=status,
        target=target,
        resource_id=resource_id,
        detail={} if detail is None else dict(detail),
    )
    return emit_event(sink, event)


def emit_approval_event(
    sink: TelemetryEmitter | TelemetrySink,
    *,
    event_id: str,
    name: str,
    decision: ApprovalDecision,
    policy_id: str,
    risk_class: str,
    request_kind: str,
    episode_id: str | None = None,
    source: str = "unknown",
    reason: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_event_id: str | None = None,
    attributes: Mapping[str, Any] | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event = ApprovalTelemetryEvent(
        metadata=TelemetryMetadata(
            event_id=event_id,
            episode_id=episode_id,
            source=source,
            trace_id=trace_id,
            span_id=span_id,
            parent_event_id=parent_event_id,
            attributes={} if attributes is None else dict(attributes),
        ),
        name=name,
        decision=decision,
        policy_id=policy_id,
        risk_class=risk_class,
        request_kind=request_kind,
        reason=reason,
        detail={} if detail is None else dict(detail),
    )
    return emit_event(sink, event)


def emit_delivery_event(
    sink: TelemetryEmitter | TelemetrySink,
    *,
    event_id: str,
    name: str,
    channel: str,
    status: DeliveryStatus,
    episode_id: str | None = None,
    source: str = "unknown",
    destination: str | None = None,
    payload_kind: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_event_id: str | None = None,
    attributes: Mapping[str, Any] | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event = DeliveryTelemetryEvent(
        metadata=TelemetryMetadata(
            event_id=event_id,
            episode_id=episode_id,
            source=source,
            trace_id=trace_id,
            span_id=span_id,
            parent_event_id=parent_event_id,
            attributes={} if attributes is None else dict(attributes),
        ),
        name=name,
        channel=channel,
        status=status,
        destination=destination,
        payload_kind=payload_kind,
        detail={} if detail is None else dict(detail),
    )
    return emit_event(sink, event)


def emit_failure_event(
    sink: TelemetryEmitter | TelemetrySink,
    *,
    event_id: str,
    name: str,
    error_kind: str,
    severity: FailureSeverity,
    recoverable: bool,
    episode_id: str | None = None,
    source: str = "unknown",
    status: Literal["failed"] = "failed",
    operation: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_event_id: str | None = None,
    attributes: Mapping[str, Any] | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event = FailureTelemetryEvent(
        metadata=TelemetryMetadata(
            event_id=event_id,
            episode_id=episode_id,
            source=source,
            trace_id=trace_id,
            span_id=span_id,
            parent_event_id=parent_event_id,
            attributes={} if attributes is None else dict(attributes),
        ),
        name=name,
        error_kind=error_kind,
        severity=severity,
        recoverable=recoverable,
        status=status,
        operation=operation,
        detail={} if detail is None else dict(detail),
    )
    return emit_event(sink, event)
