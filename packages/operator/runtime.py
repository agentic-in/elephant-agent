"""Owner-aligned operator projections and shared surface wording for CSR-6."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from packages.contracts import (
    ElephantIdentityRecord,
    ProcedureRecord,
)
from packages.contracts.runtime import RecallEvidence
from packages.state.rendered_views import RenderedRelationshipView, RenderedUserProfileView


OperatorHealthState = Literal[
    "ok",
    "degraded",
    "stopped",
    "stale",
    "misconfigured",
    "unauthorized",
    "unknown",
]
OperatorFreshness = Literal["cached", "probed", "synthetic", "unknown"]
OperatorIssueSeverity = Literal["info", "warning", "error"]
OperatorApprovalClass = Literal["none", "standard", "strict"]
OperatorActionResult = Literal["planned", "applied", "blocked", "failed"]


_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "auth",
    "credential",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True, slots=True)
class OperatorDiagnosticIssue:
    code: str
    severity: OperatorIssueSeverity
    message: str
    hint: str = ""
    repair_action_id: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OperatorComponentStatus:
    component: str
    state: OperatorHealthState
    summary: str
    details: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[OperatorDiagnosticIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class OperatorStatusReport:
    status: OperatorHealthState
    generated_at: datetime
    freshness: OperatorFreshness
    scope: str
    snapshot_id: str
    components: tuple[OperatorComponentStatus, ...] = ()
    issues: tuple[OperatorDiagnosticIssue, ...] = ()
    redactions_applied: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OperatorActionPlan:
    plan_id: str
    action: str
    base_snapshot_id: str
    required_approval: OperatorApprovalClass
    expected_changes: tuple[str, ...]
    risks: tuple[str, ...] = ()
    rollback: tuple[str, ...] = ()
    expires_at: datetime | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OperatorActionReceipt:
    receipt_id: str
    plan_id: str
    action: str
    result: OperatorActionResult
    started_at: datetime
    finished_at: datetime
    changes_applied: tuple[str, ...] = ()
    verification: Mapping[str, Any] = field(default_factory=dict)
    rollback_hint: str = ""
    redactions_applied: tuple[str, ...] = ()


def build_operator_status_report(
    *,
    scope: str = "summary",
    freshness: OperatorFreshness = "cached",
    components: tuple[OperatorComponentStatus, ...] = (),
    issues: tuple[OperatorDiagnosticIssue, ...] = (),
    generated_at: datetime | None = None,
    snapshot_id: str = "",
) -> OperatorStatusReport:
    generated = generated_at or datetime.now(timezone.utc)
    resolved_snapshot = snapshot_id or f"operator-snapshot:{generated.isoformat()}"
    return OperatorStatusReport(
        status=_rollup_operator_state(components, issues),
        generated_at=generated,
        freshness=freshness,
        scope=scope,
        snapshot_id=resolved_snapshot,
        components=components,
        issues=issues,
        redactions_applied=("secret-like keys",),
    )


def operator_status_report_record(report: OperatorStatusReport) -> dict[str, Any]:
    return {
        "status": report.status,
        "generatedAt": report.generated_at.isoformat(),
        "freshness": report.freshness,
        "scope": report.scope,
        "snapshotId": report.snapshot_id,
        "components": [
            {
                "component": component.component,
                "state": component.state,
                "summary": component.summary,
                "details": redact_operator_value(component.details),
                "issues": [_operator_issue_record(issue) for issue in component.issues],
            }
            for component in report.components
        ],
        "issues": [_operator_issue_record(issue) for issue in report.issues],
        "redactionsApplied": list(report.redactions_applied),
    }


def operator_action_plan_record(plan: OperatorActionPlan) -> dict[str, Any]:
    return {
        "planId": plan.plan_id,
        "action": plan.action,
        "baseSnapshotId": plan.base_snapshot_id,
        "requiredApproval": plan.required_approval,
        "expectedChanges": list(plan.expected_changes),
        "risks": list(plan.risks),
        "rollback": list(plan.rollback),
        "expiresAt": plan.expires_at.isoformat() if plan.expires_at else None,
        "parameters": redact_operator_value(plan.parameters),
    }


def operator_action_receipt_record(receipt: OperatorActionReceipt) -> dict[str, Any]:
    return {
        "receiptId": receipt.receipt_id,
        "planId": receipt.plan_id,
        "action": receipt.action,
        "result": receipt.result,
        "startedAt": receipt.started_at.isoformat(),
        "finishedAt": receipt.finished_at.isoformat(),
        "changesApplied": list(receipt.changes_applied),
        "verification": redact_operator_value(receipt.verification),
        "rollbackHint": receipt.rollback_hint,
        "redactionsApplied": list(receipt.redactions_applied),
    }


def operator_error_envelope(
    *,
    code: str,
    message: str,
    hint: str = "",
    retryable: bool = False,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "hint": hint,
            "retryable": retryable,
        },
    }


def redact_operator_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_secret_key(key_text):
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = redact_operator_value(item)
        return redacted
    if isinstance(value, tuple):
        return tuple(redact_operator_value(item) for item in value)
    if isinstance(value, list):
        return [redact_operator_value(item) for item in value]
    return value


def _operator_issue_record(issue: OperatorDiagnosticIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "severity": issue.severity,
        "message": issue.message,
        "hint": issue.hint,
        "repairActionId": issue.repair_action_id,
        "evidence": redact_operator_value(issue.evidence),
    }


def _rollup_operator_state(
    components: tuple[OperatorComponentStatus, ...],
    issues: tuple[OperatorDiagnosticIssue, ...],
) -> OperatorHealthState:
    if any(issue.severity == "error" for issue in issues):
        return "degraded"
    states = {component.state for component in components}
    if not states:
        return "unknown"
    if states == {"ok"}:
        return "ok"
    if "unauthorized" in states:
        return "unauthorized"
    if "misconfigured" in states:
        return "misconfigured"
    if "stale" in states:
        return "stale"
    if "stopped" in states:
        return "stopped"
    if "degraded" in states:
        return "degraded"
    return "unknown"


def _is_secret_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


@dataclass(frozen=True, slots=True)
class ProfileOperatorSurface:
    session_id: str
    profile_id: str
    profile_mode: str
    identity: ElephantIdentityRecord
    user: RenderedUserProfileView
    relationship: RenderedRelationshipView
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecallEvidenceOperatorDetail:
    evidence: RecallEvidence
    state: object | None
    lineage: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecallEvidenceSearchHit:
    evidence: RecallEvidence
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecallEvidenceOperatorSurface:
    session_id: str
    evidence_items: tuple[RecallEvidenceOperatorDetail, ...]
    search_query: str | None = None
    search_hits: tuple[RecallEvidenceSearchHit, ...] = ()
    scope_reason: str = ""
    index_policy: EmbeddingIndexPolicy | None = None


@dataclass(frozen=True, slots=True)
class ProcedureOperatorDetail:
    procedure: ProcedureRecord
    source_id: str | None = None
    maturity_state: str = ""
    approval_state: str = ""
    behavioral_state: str = ""


@dataclass(frozen=True, slots=True)
class ProcedureOperatorSurface:
    session_id: str
    profile_id: str
    procedures: tuple[ProcedureOperatorDetail, ...]


@dataclass(frozen=True, slots=True)
class DashboardMetric:
    label: str
    value: str
    note: str
    tone: str


@dataclass(frozen=True, slots=True)
class DashboardAlert:
    title: str
    detail: str
    tone: str


@dataclass(frozen=True, slots=True)
class DashboardTimelineEvent:
    label: str
    summary: str
    age: str
    tone: str


@dataclass(frozen=True, slots=True)
class DashboardProviderReadiness:
    status: str
    provider: str
    transport: str
    strong_model: str
    weak_model: str
    secret_status: str
    embedding_status: str
    summary: str
    tone: str


@dataclass(frozen=True, slots=True)
class DashboardHeartbeat:
    mode: str
    summary: str
    backlog: str
    scheduled_jobs: str
    last_success: str
    last_failure: str
    next_run: str
    tone: str


@dataclass(frozen=True, slots=True)
class DashboardProgressionRecord:
    title: str
    cycle: str
    level: str
    momentum: str
    challenge: str
    proof: str
    rollout: str
    fallback: str
    tone: str


@dataclass(frozen=True, slots=True)
class DashboardOverviewSurface:
    metrics: tuple[DashboardMetric, ...]
    alerts: tuple[DashboardAlert, ...]
    timeline: tuple[DashboardTimelineEvent, ...]
    provider: DashboardProviderReadiness | None = None
    heartbeat: DashboardHeartbeat | None = None
    progression: DashboardProgressionRecord | None = None


@dataclass(frozen=True, slots=True)
class DashboardEggRecord:
    elephant: str
    focus: str
    provider: str
    continuity: str
    last_contact: str
    tone: str
    details: tuple["DashboardDetailItem", ...] = ()

@dataclass(frozen=True, slots=True)
class DashboardDetailItem:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class DashboardStateLaneRecord:
    lane: str
    projection: str
    anchor: str
    focus: str
    state: str
    blocker: str
    support_path: str
    projection_health: str
    note: str
    tone: str
    stats: tuple[DashboardDetailItem, ...] = ()
    sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DashboardSessionRecord:
    thread: str
    conversation: str
    log: str
    model: str
    tokens: str
    usage: str
    continuity: str
    last_touch: str
    tone: str
    details: tuple[DashboardDetailItem, ...] = ()

@dataclass(frozen=True, slots=True)
class DashboardOpsRecord:
    lane: str
    event: str
    source: str
    summary: str
    outcome: str
    age: str
    tone: str


@dataclass(frozen=True, slots=True)
class DashboardCapabilityRecord:
    capability: str
    source: str
    state: str
    provenance: str
    note: str
    tone: str
    details: tuple[DashboardDetailItem, ...] = ()


@dataclass(frozen=True, slots=True)
class DashboardProviderProfileRecord:
    provider: str
    profile: str
    state: str
    auth: str
    model: str
    note: str
    tone: str
    details: tuple[DashboardDetailItem, ...] = ()


@dataclass(frozen=True, slots=True)
class DashboardControlRecord:
    control: str
    surface: str
    state: str
    boundary: str
    note: str
    tone: str
    details: tuple[DashboardDetailItem, ...] = ()


@dataclass(frozen=True, slots=True)
class DashboardMeta:
    scenario: str
    source_label: str
    shell_status: str
    generated_at: str
    note: str
    query_contract: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DashboardSurface:
    meta: DashboardMeta
    overview: DashboardOverviewSurface
    herd: tuple[DashboardEggRecord, ...] = ()
    state_lanes: tuple[DashboardStateLaneRecord, ...] = ()
    sessions: tuple[DashboardSessionRecord, ...] = ()
    ops: tuple[DashboardOpsRecord, ...] = ()
    capabilities: tuple[DashboardCapabilityRecord, ...] = ()
    provider_profiles: tuple[DashboardProviderProfileRecord, ...] = ()
    controls: tuple[DashboardControlRecord, ...] = ()


DEFAULT_DASHBOARD_QUERY_CONTRACT = (
    "Read-first shell over canonical runtime state; the dashboard is not a source of truth.",
    "Default 30-second polling with a manual refresh and visible projection time.",
    "The product dashboard only renders live local operator state; unavailable, empty, stale, and degraded states stay visible as real states.",
)


def build_profile_operator_surface(
    *,
    session_id: str,
    profile_id: str,
    profile_mode: str,
    identity: ElephantIdentityRecord,
    user: RenderedUserProfileView,
    relationship: RenderedRelationshipView,
    provenance: tuple[str, ...] = (),
) -> ProfileOperatorSurface:
    return ProfileOperatorSurface(
        session_id=session_id,
        profile_id=profile_id,
        profile_mode=profile_mode,
        identity=identity,
        user=user,
        relationship=relationship,
        provenance=provenance or ("state.identity", "pm_facts.user_profile_view", "pm_facts.relationship_view"),
    )


def build_recall_evidence_operator_surface(
    *,
    session_id: str,
    evidence_items: tuple[RecallEvidenceOperatorDetail, ...],
    search_query: str | None = None,
    search_hits: tuple[RecallEvidenceSearchHit, ...] = (),
    scope_reason: str = "",
    index_policy: EmbeddingIndexPolicy | None = None,
) -> RecallEvidenceOperatorSurface:
    return RecallEvidenceOperatorSurface(
        session_id=session_id,
        evidence_items=evidence_items,
        search_query=search_query,
        search_hits=search_hits,
        scope_reason=scope_reason,
        index_policy=index_policy,
    )


def build_procedure_operator_surface(
    *,
    session_id: str,
    profile_id: str,
    procedures: tuple[ProcedureOperatorDetail, ...],
) -> ProcedureOperatorSurface:
    return ProcedureOperatorSurface(
        session_id=session_id,
        profile_id=profile_id,
        procedures=procedures,
    )


def build_canonical_procedure_detail(
    *,
    procedure: ProcedureRecord,
    source_id: str,
    maturity_state: str = "",
    approval_state: str = "",
    behavioral_state: str = "",
) -> ProcedureOperatorDetail:
    return ProcedureOperatorDetail(
        procedure=procedure,
        source_id=source_id,
        maturity_state=maturity_state,
        approval_state=approval_state,
        behavioral_state=behavioral_state,
    )


def build_dashboard_surface(
    *,
    scenario: str,
    source_label: str,
    shell_status: str,
    generated_at: str,
    note: str,
    metrics: tuple[DashboardMetric, ...],
    alerts: tuple[DashboardAlert, ...],
    timeline: tuple[DashboardTimelineEvent, ...],
    herd: tuple[DashboardEggRecord, ...],
    state_lanes: tuple[DashboardStateLaneRecord, ...] = (),
    sessions: tuple[DashboardSessionRecord, ...] = (),
    ops: tuple[DashboardOpsRecord, ...] = (),
    capabilities: tuple[DashboardCapabilityRecord, ...] = (),
    provider_profiles: tuple[DashboardProviderProfileRecord, ...] = (),
    controls: tuple[DashboardControlRecord, ...] = (),
    provider: DashboardProviderReadiness | None = None,
    heartbeat: DashboardHeartbeat | None = None,
    progression: DashboardProgressionRecord | None = None,
    query_contract: tuple[str, ...] = (),
) -> DashboardSurface:
    return DashboardSurface(
        meta=DashboardMeta(
            scenario=scenario,
            source_label=source_label,
            shell_status=shell_status,
            generated_at=generated_at,
            note=note,
            query_contract=query_contract or DEFAULT_DASHBOARD_QUERY_CONTRACT,
        ),
        overview=DashboardOverviewSurface(
            metrics=metrics,
            alerts=alerts,
            timeline=timeline,
            provider=provider,
            heartbeat=heartbeat,
            progression=progression,
        ),
        herd=herd,
        state_lanes=state_lanes,
        sessions=sessions,
        ops=ops,
        capabilities=capabilities,
        provider_profiles=provider_profiles,
        controls=controls,
    )


def dashboard_surface_record(surface: DashboardSurface) -> dict[str, object]:
    provider = surface.overview.provider
    heartbeat = surface.overview.heartbeat
    progression = surface.overview.progression
    return {
        "meta": {
            "scenario": surface.meta.scenario,
            "sourceLabel": surface.meta.source_label,
            "shellStatus": surface.meta.shell_status,
            "generatedAt": surface.meta.generated_at,
            "note": surface.meta.note,
            "queryContract": list(surface.meta.query_contract),
        },
        "overview": {
            "metrics": [
                {
                    "label": metric.label,
                    "value": metric.value,
                    "note": metric.note,
                    "tone": metric.tone,
                }
                for metric in surface.overview.metrics
            ],
            "alerts": [
                {
                    "title": alert.title,
                    "detail": alert.detail,
                    "tone": alert.tone,
                }
                for alert in surface.overview.alerts
            ],
            "timeline": [
                {
                    "label": event.label,
                    "summary": event.summary,
                    "age": event.age,
                    "tone": event.tone,
                }
                for event in surface.overview.timeline
            ],
            "provider": (
                {
                    "status": provider.status,
                    "provider": provider.provider,
                    "transport": provider.transport,
                    "strongModel": provider.strong_model,
                    "weakModel": provider.weak_model,
                    "secretStatus": provider.secret_status,
                    "embeddingStatus": provider.embedding_status,
                    "summary": provider.summary,
                    "tone": provider.tone,
                }
                if provider is not None
                else None
            ),
            "heartbeat": (
                {
                    "mode": heartbeat.mode,
                    "summary": heartbeat.summary,
                    "backlog": heartbeat.backlog,
                    "scheduledJobs": heartbeat.scheduled_jobs,
                    "lastSuccess": heartbeat.last_success,
                    "lastFailure": heartbeat.last_failure,
                    "nextRun": heartbeat.next_run,
                    "tone": heartbeat.tone,
                }
                if heartbeat is not None
                else None
            ),
            "progression": (
                {
                    "title": progression.title,
                    "cycle": progression.cycle,
                    "level": progression.level,
                    "momentum": progression.momentum,
                    "challenge": progression.challenge,
                    "proof": progression.proof,
                    "rollout": progression.rollout,
                    "fallback": progression.fallback,
                    "tone": progression.tone,
                }
                if progression is not None
                else None
            ),
        },
        "herd": [
            {
                "elephant": elephant.elephant,
                "focus": elephant.focus,
                "provider": elephant.provider,
                "continuity": elephant.continuity,
                "lastContact": elephant.last_contact,
                "tone": elephant.tone,
                "details": [
                    {
                        "label": item.label,
                        "value": item.value,
                    }
                    for item in elephant.details
                ],
            }
            for elephant in surface.herd
        ],
        "stateLanes": [
            {
                "lane": lane.lane,
                "projection": lane.projection,
                "anchor": lane.anchor,
                "focus": lane.focus,
                "state": lane.state,
                "blocker": lane.blocker,
                "supportPath": lane.support_path,
                "projectionHealth": lane.projection_health,
                "note": lane.note,
                "tone": lane.tone,
                "stats": [
                    {
                        "label": item.label,
                        "value": item.value,
                    }
                    for item in lane.stats
                ],
                "sources": list(lane.sources),
            }
            for lane in surface.state_lanes
        ],
        "sessions": [
            {
                "thread": session.thread,
                "conversation": session.conversation,
                "log": session.log,
                "model": session.model,
                "tokens": session.tokens,
                "usage": session.usage,
                "continuity": session.continuity,
                "lastTouch": session.last_touch,
                "tone": session.tone,
                "details": [
                    {
                        "label": item.label,
                        "value": item.value,
                    }
                    for item in session.details
                ],
            }
            for session in surface.sessions
        ],
        "ops": [
            {
                "lane": event.lane,
                "event": event.event,
                "source": event.source,
                "summary": event.summary,
                "outcome": event.outcome,
                "age": event.age,
                "tone": event.tone,
            }
            for event in surface.ops
        ],
        "capabilities": [
            {
                "capability": capability.capability,
                "source": capability.source,
                "state": capability.state,
                "provenance": capability.provenance,
                "note": capability.note,
                "tone": capability.tone,
                "details": [
                    {
                        "label": item.label,
                        "value": item.value,
                    }
                    for item in capability.details
                ],
            }
            for capability in surface.capabilities
        ],
        "providerProfiles": [
            {
                "provider": provider_profile.provider,
                "profile": provider_profile.profile,
                "state": provider_profile.state,
                "auth": provider_profile.auth,
                "model": provider_profile.model,
                "note": provider_profile.note,
                "tone": provider_profile.tone,
                "details": [
                    {
                        "label": item.label,
                        "value": item.value,
                    }
                    for item in provider_profile.details
                ],
            }
            for provider_profile in surface.provider_profiles
        ],
        "controls": [
            {
                "control": control.control,
                "surface": control.surface,
                "state": control.state,
                "boundary": control.boundary,
                "note": control.note,
                "tone": control.tone,
                "details": [
                    {
                        "label": item.label,
                        "value": item.value,
                    }
                    for item in control.details
                ],
            }
            for control in surface.controls
        ],
    }


def render_profile_lines(surface: ProfileOperatorSurface) -> tuple[str, ...]:
    return (
        f"profile_id: {surface.profile_id}",
        f"profile_mode: {surface.profile_mode}",
        f"identity_display_name: {surface.identity.display_name}",
        f"identity_preset: {surface.identity.personality_preset}",
        f"identity_initiative: {surface.identity.initiative}",
        f"user_preferred_name: {surface.user.preferred_name or '<empty>'}",
        f"user_biography_fragments: {', '.join(surface.user.biography_fragments) or '<empty>'}",
        f"user_durable_notes: {', '.join(surface.user.durable_notes) or '<empty>'}",
        f"user_shared_preferences: {', '.join(surface.user.shared_preferences) or '<empty>'}",
        f"relationship_notes: {', '.join(surface.relationship.continuity_notes) or '<empty>'}",
        f"provenance: {', '.join(surface.provenance)}",
    )


def render_recall_evidence_lines(surface: RecallEvidenceOperatorSurface) -> tuple[str, ...]:
    lines: list[str] = []
    for item in surface.evidence_items:
        lines.append(
            f"{item.evidence.evidence_id} | state={item.state or 'active'} | lineage={', '.join(item.lineage) or 'none'} | "
            f"tags={', '.join(item.evidence.tags) or 'none'} | {item.evidence.kind} | {item.evidence.content}"
        )
    if not lines:
        lines.append("<empty>")
    if surface.search_query is not None:
        lines.extend(("", f"search_query: {surface.search_query}", f"scope_reason: {surface.scope_reason or '<none>'}"))
        for hit in surface.search_hits:
            lines.append(
                f"- {hit.evidence.evidence_id} | score={hit.score:.2f} | reasons={'; '.join(hit.reasons) or '<none>'} | {hit.evidence.content}"
            )
    return tuple(lines)


def render_procedure_lines(surface: ProcedureOperatorSurface) -> tuple[str, ...]:
    lines = [f"profile_id: {surface.profile_id}", f"procedure_count: {len(surface.procedures)}"]
    if surface.procedures:
        lines.append("procedures:")
        lines.extend(
            (
                f"- {detail.procedure.procedure_id} | {detail.procedure.status} | "
                f"maturity={detail.maturity_state or 'unknown'} | "
                f"approval={detail.approval_state or 'unknown'} | "
                f"skill={detail.procedure.skill_id or 'none'} | "
                f"{detail.procedure.title}"
            )
            for detail in surface.procedures
        )
    if len(lines) == 3:
        lines.append("<empty>")
    return tuple(lines)


__all__ = [
    "DashboardAlert",
    "DashboardEggRecord",
    "DashboardDetailItem",
    "DashboardHeartbeat",
    "DashboardStateLaneRecord",
    "DashboardMeta",
    "DashboardMetric",
    "DashboardOpsRecord",
    "DashboardOverviewSurface",
    "DashboardProgressionRecord",
    "DashboardProviderReadiness",
    "DashboardSessionRecord",
    "DashboardSurface",
    "DashboardTimelineEvent",
    "RecallEvidenceOperatorDetail",
    "RecallEvidenceOperatorSurface",
    "RecallEvidenceSearchHit",
    "ProcedureOperatorDetail",
    "ProcedureOperatorSurface",
    "ProfileOperatorSurface",
    "build_dashboard_surface",
    "build_recall_evidence_operator_surface",
    "build_procedure_operator_surface",
    "build_profile_operator_surface",
    "dashboard_surface_record",
    "render_recall_evidence_lines",
    "render_procedure_lines",
    "render_profile_lines",
]
