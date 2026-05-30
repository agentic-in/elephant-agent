"""Approval gateway implementations for governed tool execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from packages.security import (
    ApprovalClass,
    PolicyDecision,
    SecurityPolicy,
    SecurityRequest,
    evaluate_with_telemetry,
)

from .runtime import (
    ToolApprovalDecision,
    ToolApprovalResult,
    ToolDefinition,
    ToolInvocation,
    ToolSideEffectMetadata,
)


@dataclass(frozen=True, slots=True)
class SecurityApprovalGateway:
    policy: SecurityPolicy
    telemetry: object
    source: str = "tool.runtime"
    auto_approve_deferred: bool = False

    def authorize(
        self,
        definition: ToolDefinition,
        invocation: ToolInvocation,
    ) -> ToolApprovalResult:
        request = _security_request_for_tool(definition, invocation)
        if request is None:
            return ToolApprovalResult(
                decision="approved",
                risk_class=definition.side_effects.risk_class,
                reason="No approval class was configured for this tool invocation.",
            )
        result = evaluate_with_telemetry(
            self.policy,
            request,
            self.telemetry,
            source=self.source,
        )
        decision = _tool_decision_from_policy(result.decision)
        reason = result.rationale
        approval_token: str | None = None
        if decision == "deferred":
            approval_token = f"approval:{invocation.invocation_id}"
            if self.auto_approve_deferred:
                decision = "approved"
                approval_token = f"auto:{invocation.invocation_id}"
                reason = (
                    f"{result.rationale} Auto-approved on {self.source} "
                    "until an external approval surface is configured."
                )
        return ToolApprovalResult(
            decision=decision,
            risk_class=result.risk_level.value,
            required_controls=result.required_controls,
            reason=reason,
            approval_token=approval_token,
        )


@dataclass(frozen=True, slots=True)
class CallableApprovalGateway:
    policy: Callable[[ToolDefinition, ToolInvocation], bool]

    def authorize(
        self,
        definition: ToolDefinition,
        invocation: ToolInvocation,
    ) -> ToolApprovalResult:
        approved = self.policy(definition, invocation)
        return ToolApprovalResult(
            decision="approved" if approved else "denied",
            risk_class=definition.side_effects.risk_class,
            reason=(
                "approved by callable approval gateway"
                if approved
                else "blocked by callable approval gateway"
            ),
        )


def _tool_decision_from_policy(decision: PolicyDecision) -> ToolApprovalDecision:
    if decision == PolicyDecision.ALLOW:
        return "approved"
    if decision == PolicyDecision.DENY:
        return "denied"
    return "deferred"


def _security_request_for_tool(
    definition: ToolDefinition,
    invocation: ToolInvocation,
) -> SecurityRequest | None:
    approval_class = _resolve_approval_class(definition.side_effects)
    if approval_class is None:
        return None
    return SecurityRequest(
        request_id=f"req:tool:{invocation.invocation_id}",
        approval_class=approval_class,
        operation=definition.tool_id,
        episode_id=invocation.session_id,
        description=definition.description or definition.display_name,
        is_external=definition.side_effects.touches_network,
        is_destructive=definition.side_effects.writes_state,
        consent_given=False,
        target_trusted=False,
        metadata={
            "tool_id": definition.tool_id,
            "approval_class": approval_class.value,
            "risk_class": definition.side_effects.risk_class,
            "surface_id": invocation.context.surface_id,
            "surface_kind": invocation.context.surface_kind,
            "state_id": invocation.context.state_id,
            "personal_model_id": invocation.context.personal_model_id,
            "elephant_id": invocation.context.elephant_id,
        },
    )


def _resolve_approval_class(side_effects: ToolSideEffectMetadata) -> ApprovalClass | None:
    raw = side_effects.approval_class.strip().lower()
    if raw in {"", "none"}:
        return None
    for approval_class in ApprovalClass:
        if raw == approval_class.value:
            return approval_class
    if raw == "strict":
        if side_effects.touches_network:
            return ApprovalClass.NETWORK
        if side_effects.writes_state and side_effects.reads_state:
            return ApprovalClass.EXEC
        if side_effects.writes_state:
            return ApprovalClass.WRITE
        return ApprovalClass.EXEC
    if raw == "standard":
        if side_effects.touches_network:
            return ApprovalClass.NETWORK
        if side_effects.writes_state:
            return ApprovalClass.WRITE
        return ApprovalClass.READ
    return ApprovalClass.WRITE if side_effects.writes_state else ApprovalClass.READ
