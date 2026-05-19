"""Typed approval taxonomy and policy evaluation primitives.

This module intentionally stays independent from the rest of the runtime
packages so security policy can be reused by tools, gateway adapters, voice,
and future deploy controls without import cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Mapping

from packages.telemetry.runtime import (
    ApprovalDecision as TelemetryApprovalDecision,
    FailureSeverity,
    TelemetryEmitter,
    TelemetrySink,
    emit_approval_event,
    emit_failure_event,
)

_REDACTED = "***"
_SAFE_METADATA_KEYS = {"approval_class", "request_id", "rule_id"}
_SENSITIVE_DETAIL_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "secret",
    "token",
    "x_api_key",
    "x_auth_token",
}
_SECRET_TEXT_PATTERNS = (
    (
        re.compile(r"(?i)\b(bearer)\s+[a-z0-9._~+/=-]{8,}\b"),
        lambda match: f"{match.group(1)} {_REDACTED}",
    ),
    (
        re.compile(r"(?i)\b(api[_-]?key|authorization|token|secret|password)(\s*[:=]\s*)([^,\s;\"']+)"),
        lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}",
    ),
    (
        re.compile(r"\bsk(?:-[a-zA-Z0-9_-]{6,}|_proj-[a-zA-Z0-9_-]{6,})\b"),
        lambda _match: _REDACTED,
    ),
    (
        re.compile(
            r"(?i)(-----BEGIN [A-Z ]*PRIVATE KEY-----)(.*?)(-----END [A-Z ]*PRIVATE KEY-----)",
            re.DOTALL,
        ),
        lambda match: f"{match.group(1)}\n{_REDACTED}\n{match.group(3)}",
    ),
)


def _normalize_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").lower()


def _redact_text(value: str) -> str:
    redacted = value
    for pattern, replacer in _SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(replacer, redacted)
    redacted = re.sub(r"\*\*\*(?:\s+\*\*\*)+", _REDACTED, redacted)
    return redacted


def _redact_detail(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, Mapping):
        return {entry_key: _redact_detail(entry_value, key=str(entry_key)) for entry_key, entry_value in value.items()}
    if isinstance(value, tuple):
        return tuple(_redact_detail(item, key=key) for item in value)
    if isinstance(value, list):
        return [_redact_detail(item, key=key) for item in value]
    if isinstance(value, str):
        normalized_key = _normalize_key(key) if key is not None else ""
        if normalized_key in _SENSITIVE_DETAIL_KEYS and normalized_key not in _SAFE_METADATA_KEYS:
            return _REDACTED
        return _redact_text(value)
    return value


class ApprovalClass(str, Enum):
    READ = "read"
    WRITE = "write"
    EXEC = "exec"
    NETWORK = "network"
    MESSAGING = "messaging"
    VOICE_DEVICE = "voice-device"


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"

    def escalated(self) -> "RiskLevel":
        levels = (
            RiskLevel.LOW,
            RiskLevel.MODERATE,
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        )
        index = levels.index(self)
        return levels[min(index + 1, len(levels) - 1)]


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_CONSENT = "allow_with_consent"
    REVIEW = "review"
    DENY = "deny"

    @property
    def is_terminal(self) -> bool:
        return self in {PolicyDecision.ALLOW, PolicyDecision.DENY}


@dataclass(frozen=True, slots=True)
class SecurityRequest:
    request_id: str
    approval_class: ApprovalClass
    operation: str
    episode_id: str | None = None
    description: str | None = None
    is_external: bool = False
    is_destructive: bool = False
    consent_given: bool = False
    recording_enabled: bool = False
    target_trusted: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyRule:
    rule_id: str
    approval_class: ApprovalClass
    risk_level: RiskLevel
    default_decision: PolicyDecision
    required_controls: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class PolicyResult:
    request_id: str
    approval_class: ApprovalClass
    decision: PolicyDecision
    risk_level: RiskLevel
    rule_id: str
    rationale: str
    required_controls: tuple[str, ...] = ()
    audit_tags: tuple[str, ...] = ()
    matched_factors: tuple[str, ...] = ()

    @property
    def approved(self) -> bool:
        return self.decision == PolicyDecision.ALLOW

    def to_audit_event(self) -> "SecurityAuditEvent":
        return SecurityAuditEvent(
            event_id=f"audit:{self.request_id}",
            request_id=self.request_id,
            approval_class=self.approval_class,
            decision=self.decision,
            risk_level=self.risk_level,
            summary=self.rationale,
            required_controls=self.required_controls,
            audit_tags=self.audit_tags,
        )


@dataclass(frozen=True, slots=True)
class SecurityAuditEvent:
    event_id: str
    request_id: str
    approval_class: ApprovalClass
    decision: PolicyDecision
    risk_level: RiskLevel
    summary: str
    required_controls: tuple[str, ...] = ()
    audit_tags: tuple[str, ...] = ()

    def to_record(self) -> dict[str, str | tuple[str, ...]]:
        return {
            "event_id": self.event_id,
            "request_id": self.request_id,
            "approval_class": self.approval_class.value,
            "decision": self.decision.value,
            "risk_level": self.risk_level.value,
            "summary": _redact_text(self.summary),
            "required_controls": tuple(_redact_detail(self.required_controls)),
            "audit_tags": tuple(_redact_detail(self.audit_tags)),
        }


@dataclass(frozen=True, slots=True)
class SurfacePolicyBundle:
    surface_id: str
    label: str
    approval_classes: tuple[ApprovalClass, ...]
    summary: str

    def to_record(self, policy: "SecurityPolicy") -> dict[str, object]:
        classes: list[dict[str, object]] = []
        for approval_class in self.approval_classes:
            rule = policy.rule_for(approval_class)
            if rule is None:
                classes.append(
                    {
                        "approval_class": approval_class.value,
                        "decision": PolicyDecision.DENY.value,
                        "risk_level": RiskLevel.CRITICAL.value,
                        "required_controls": ("register-policy-rule",),
                    }
                )
                continue
            classes.append(
                {
                    "approval_class": approval_class.value,
                    "decision": rule.default_decision.value,
                    "risk_level": rule.risk_level.value,
                    "required_controls": rule.required_controls,
                }
            )
        return {
            "surface_id": self.surface_id,
            "label": self.label,
            "summary": self.summary,
            "approval_classes": classes,
        }


def _controls(*values: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def default_policy_rules() -> dict[ApprovalClass, PolicyRule]:
    return {
        ApprovalClass.READ: PolicyRule(
            rule_id="read-default",
            approval_class=ApprovalClass.READ,
            risk_level=RiskLevel.LOW,
            default_decision=PolicyDecision.ALLOW,
            required_controls=_controls("audit-read"),
            rationale="Read operations are low risk when scoped to the active session.",
        ),
        ApprovalClass.WRITE: PolicyRule(
            rule_id="write-default",
            approval_class=ApprovalClass.WRITE,
            risk_level=RiskLevel.MODERATE,
            default_decision=PolicyDecision.ALLOW_WITH_CONSENT,
            required_controls=_controls("audit-write", "confirm-change"),
            rationale="Writes require explicit acknowledgement because they may mutate durable state.",
        ),
        ApprovalClass.EXEC: PolicyRule(
            rule_id="exec-default",
            approval_class=ApprovalClass.EXEC,
            risk_level=RiskLevel.HIGH,
            default_decision=PolicyDecision.REVIEW,
            required_controls=_controls("sandbox", "explicit-approval"),
            rationale="Execution surfaces can trigger arbitrary side effects or host access.",
        ),
        ApprovalClass.NETWORK: PolicyRule(
            rule_id="network-default",
            approval_class=ApprovalClass.NETWORK,
            risk_level=RiskLevel.HIGH,
            default_decision=PolicyDecision.REVIEW,
            required_controls=_controls("outbound-policy", "destination-check"),
            rationale="Network access must be reviewed because it crosses the local trust boundary.",
        ),
        ApprovalClass.MESSAGING: PolicyRule(
            rule_id="messaging-default",
            approval_class=ApprovalClass.MESSAGING,
            risk_level=RiskLevel.MODERATE,
            default_decision=PolicyDecision.ALLOW_WITH_CONSENT,
            required_controls=_controls("recipient-check", "consent"),
            rationale="Messaging is allowed with consent when the recipient and content are clear.",
        ),
        ApprovalClass.VOICE_DEVICE: PolicyRule(
            rule_id="voice-device-default",
            approval_class=ApprovalClass.VOICE_DEVICE,
            risk_level=RiskLevel.HIGH,
            default_decision=PolicyDecision.ALLOW_WITH_CONSENT,
            required_controls=_controls("device-consent", "recording-boundary"),
            rationale="Voice and device access require explicit user consent and recording boundaries.",
        ),
    }


def default_surface_policy_bundles() -> tuple[SurfacePolicyBundle, ...]:
    return (
        SurfacePolicyBundle(
            surface_id="cli.operator",
            label="CLI operator path",
            approval_classes=(
                ApprovalClass.READ,
                ApprovalClass.WRITE,
                ApprovalClass.VOICE_DEVICE,
            ),
            summary="Local shell inspection, governed edits, and optional voice extension.",
        ),
        SurfacePolicyBundle(
            surface_id="gateway.messaging",
            label="Gateway messaging path",
            approval_classes=(
                ApprovalClass.READ,
                ApprovalClass.MESSAGING,
                ApprovalClass.NETWORK,
            ),
            summary="Outbound messaging and remote delivery across recipient and boundary checks.",
        ),
        SurfacePolicyBundle(
            surface_id="deploy.support",
            label="Deploy and support path",
            approval_classes=(
                ApprovalClass.READ,
                ApprovalClass.EXEC,
                ApprovalClass.NETWORK,
            ),
            summary="Install, doctor, deploy, and support collection without secret exfiltration.",
        ),
    )


class SecurityPolicy:
    def __init__(self, rules: Mapping[ApprovalClass, PolicyRule] | None = None) -> None:
        self._rules = dict(default_policy_rules() if rules is None else rules)

    @classmethod
    def default(cls) -> "SecurityPolicy":
        return cls()

    def rule_for(self, approval_class: ApprovalClass) -> PolicyRule | None:
        return self._rules.get(approval_class)

    def evaluate(self, request: SecurityRequest) -> PolicyResult:
        rule = self.rule_for(request.approval_class)
        if rule is None:
            return PolicyResult(
                request_id=request.request_id,
                approval_class=request.approval_class,
                decision=PolicyDecision.DENY,
                risk_level=RiskLevel.CRITICAL,
                rule_id="unregistered-surface",
                rationale=f"No policy rule is registered for {request.approval_class.value}.",
                required_controls=_controls("register-policy-rule"),
                audit_tags=_controls("policy-gap", request.approval_class.value),
                matched_factors=_controls("missing-rule"),
            )

        decision = rule.default_decision
        risk_level = rule.risk_level
        required_controls = list(rule.required_controls)
        matched_factors = [rule.rule_id]

        if request.is_destructive:
            matched_factors.append("destructive")
            required_controls.append("change-review")
            risk_level = risk_level.escalated()
            if decision == PolicyDecision.ALLOW:
                decision = PolicyDecision.REVIEW

        if request.is_external and request.approval_class in {
            ApprovalClass.NETWORK,
            ApprovalClass.MESSAGING,
        }:
            matched_factors.append("external")
            required_controls.append("boundary-review")
            risk_level = risk_level.escalated()
            decision = PolicyDecision.REVIEW

        if request.approval_class == ApprovalClass.VOICE_DEVICE:
            matched_factors.append("voice-boundary")
            if request.recording_enabled:
                required_controls.append("recording-consent")
                risk_level = risk_level.escalated()
                decision = PolicyDecision.REVIEW

        if request.approval_class == ApprovalClass.MESSAGING and request.target_trusted:
            matched_factors.append("trusted-target")
            if request.consent_given:
                decision = PolicyDecision.ALLOW

        if request.approval_class == ApprovalClass.MESSAGING and not request.target_trusted:
            matched_factors.append("untrusted-target")
            required_controls.append("recipient-verification")
            risk_level = risk_level.escalated()
            decision = PolicyDecision.REVIEW

        if request.approval_class == ApprovalClass.VOICE_DEVICE and request.consent_given:
            matched_factors.append("consent-given")
            if decision == PolicyDecision.ALLOW_WITH_CONSENT:
                decision = PolicyDecision.ALLOW

        if request.approval_class == ApprovalClass.WRITE and request.consent_given:
            matched_factors.append("consent-given")
            if decision == PolicyDecision.ALLOW_WITH_CONSENT:
                decision = PolicyDecision.ALLOW

        if request.approval_class == ApprovalClass.MESSAGING and not request.consent_given:
            matched_factors.append("consent-required")

        if request.approval_class == ApprovalClass.NETWORK and request.target_trusted:
            matched_factors.append("trusted-destination")
            if decision != PolicyDecision.REVIEW:
                decision = PolicyDecision.ALLOW_WITH_CONSENT

        rationale = " ".join(
            part
            for part in (
                rule.rationale,
                _rationale_tail(request, decision, risk_level),
            )
            if part
        )
        audit_tags = _controls(
            request.approval_class.value,
            rule.rule_id,
            decision.value,
            risk_level.value,
        )

        return PolicyResult(
            request_id=request.request_id,
            approval_class=request.approval_class,
            decision=decision,
            risk_level=risk_level,
            rule_id=rule.rule_id,
            rationale=rationale,
            required_controls=_controls(*required_controls),
            audit_tags=audit_tags,
            matched_factors=tuple(dict.fromkeys(matched_factors)),
        )


@dataclass(frozen=True, slots=True)
class SecurityTelemetryTrail:
    sink: TelemetryEmitter | TelemetrySink
    source: str = "security.policy"

    def evaluate(
        self,
        policy: SecurityPolicy,
        request: SecurityRequest,
    ) -> PolicyResult:
        self.emit_requested(request)
        result = policy.evaluate(request)
        self.emit_classified(request, result)
        self.emit_decided(request, result)
        self.emit_terminal_failure(request, result)
        return result

    def emit_requested(self, request: SecurityRequest) -> dict[str, object]:
        return emit_approval_event(
            self.sink,
            event_id=f"{request.request_id}:approval.requested",
            name="approval.requested",
            decision="deferred",
            policy_id="security.policy",
            risk_class="unclassified",
            request_kind=request.approval_class.value,
            episode_id=request.episode_id,
            source=self.source,
            reason=_redact_text(request.description) if request.description is not None else None,
            detail={
                "request_id": request.request_id,
                "operation": _redact_text(request.operation),
                "approval_class": request.approval_class.value,
                "metadata": _redact_detail(dict(request.metadata)),
            },
        )

    def emit_classified(
        self,
        request: SecurityRequest,
        result: PolicyResult,
    ) -> dict[str, object]:
        return emit_approval_event(
            self.sink,
            event_id=f"{request.request_id}:approval.classified",
            name="approval.classified",
            decision="deferred",
            policy_id=result.rule_id,
            risk_class=result.risk_level.value,
            request_kind=request.approval_class.value,
            episode_id=request.episode_id,
            source=self.source,
            reason=_redact_text(result.rationale),
            detail={
                "request_id": request.request_id,
                "operation": _redact_text(request.operation),
                "required_controls": _redact_detail(result.required_controls),
                "matched_factors": _redact_detail(result.matched_factors),
            },
        )

    def emit_decided(
        self,
        request: SecurityRequest,
        result: PolicyResult,
    ) -> dict[str, object]:
        decision = _telemetry_decision(result.decision)
        record = emit_approval_event(
            self.sink,
            event_id=f"{request.request_id}:approval.decided",
            name="approval.decided",
            decision=decision,
            policy_id=result.rule_id,
            risk_class=result.risk_level.value,
            request_kind=request.approval_class.value,
            episode_id=request.episode_id,
            source=self.source,
            reason=_redact_text(result.rationale),
            detail={
                "request_id": request.request_id,
                "operation": _redact_text(request.operation),
                "required_controls": _redact_detail(result.required_controls),
                "matched_factors": _redact_detail(result.matched_factors),
            },
        )
        terminal_name = None
        if decision == "approved":
            terminal_name = "approval.granted"
        elif decision == "denied":
            terminal_name = "approval.denied"
        if terminal_name is None:
            return record
        emit_approval_event(
            self.sink,
            event_id=f"{request.request_id}:{terminal_name}",
            name=terminal_name,
            decision=decision,
            policy_id=result.rule_id,
            risk_class=result.risk_level.value,
            request_kind=request.approval_class.value,
            episode_id=request.episode_id,
            source=self.source,
            reason=_redact_text(result.rationale),
            detail={
                "request_id": request.request_id,
                "operation": _redact_text(request.operation),
                "required_controls": _redact_detail(result.required_controls),
                "matched_factors": _redact_detail(result.matched_factors),
            },
        )
        return record

    def emit_terminal_failure(
        self,
        request: SecurityRequest,
        result: PolicyResult,
    ) -> dict[str, object] | None:
        if result.rule_id != "unregistered-surface" and result.decision != PolicyDecision.DENY:
            return None
        severity: FailureSeverity = "critical" if result.rule_id == "unregistered-surface" else "warning"
        error_kind = "approval_context_missing" if result.rule_id == "unregistered-surface" else "approval_denied"
        return emit_failure_event(
            self.sink,
            event_id=f"{request.request_id}:failure.side_effect.reported",
            name="failure.side_effect.reported",
            error_kind=error_kind,
            severity=severity,
            recoverable=False,
            episode_id=request.episode_id,
            source=self.source,
            operation=_redact_text(request.operation),
            detail={
                "request_id": request.request_id,
                "approval_class": request.approval_class.value,
                "rule_id": result.rule_id,
                "decision": result.decision.value,
                "required_controls": _redact_detail(result.required_controls),
            },
        )


def evaluate_with_telemetry(
    policy: SecurityPolicy,
    request: SecurityRequest,
    sink: TelemetryEmitter | TelemetrySink,
    *,
    source: str = "security.policy",
) -> PolicyResult:
    return SecurityTelemetryTrail(sink=sink, source=source).evaluate(policy, request)


def _rationale_tail(
    request: SecurityRequest,
    decision: PolicyDecision,
    risk_level: RiskLevel,
) -> str:
    bits = [
        f"decision={decision.value}",
        f"risk={risk_level.value}",
    ]
    if request.is_external:
        bits.append("external")
    if request.is_destructive:
        bits.append("destructive")
    if request.consent_given:
        bits.append("consent")
    if request.recording_enabled:
        bits.append("recording")
    if request.target_trusted:
        bits.append("trusted-target")
    return "; ".join(bits)


def _telemetry_decision(decision: PolicyDecision) -> TelemetryApprovalDecision:
    if decision == PolicyDecision.ALLOW:
        return "approved"
    if decision == PolicyDecision.DENY:
        return "denied"
    return "deferred"
