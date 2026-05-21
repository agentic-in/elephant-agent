"""Reusable operator management surface for app runtimes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from .runtime import (
    OperatorActionPlan,
    OperatorActionReceipt,
    OperatorComponentStatus,
    OperatorDiagnosticIssue,
    build_operator_status_report,
    operator_action_plan_record,
    operator_action_receipt_record,
    operator_error_envelope,
    operator_status_report_record,
    redact_operator_value,
)


ProviderSummaryReader = Callable[[], Mapping[str, Any]]
ProviderDoctorReader = Callable[[bool], Mapping[str, Any]]
ProviderDefaultWriter = Callable[[Mapping[str, Any]], Mapping[str, Any]]
DaemonStatusReader = Callable[[bool], Mapping[str, Any]]
DaemonRestartWriter = Callable[[Mapping[str, Any]], Mapping[str, Any]]
ObjectGetter = Callable[[], Any]


@dataclass(slots=True)
class OperatorRuntimeManagementSurface:
    surface_label: str
    provider_summary: ProviderSummaryReader | None = None
    provider_doctor: ProviderDoctorReader | None = None
    set_default_provider: ProviderDefaultWriter | None = None
    daemon_status: DaemonStatusReader | None = None
    daemon_restart: DaemonRestartWriter | None = None
    skill_management: Any = None
    tool_runtime: ObjectGetter | None = None
    security_policy: ObjectGetter | None = None
    _plans: dict[str, OperatorActionPlan] = field(default_factory=dict, init=False, repr=False)

    def inspect_operator(
        self,
        session_id: str,
        *,
        scope: str = "summary",
        probe: bool = False,
        include: tuple[str, ...] = (),
    ) -> Mapping[str, Any]:
        resolved_scope = _normalize_scope(scope)
        sections = self._sections_for_scope(resolved_scope, include)
        components: list[OperatorComponentStatus] = []
        for section in sections:
            components.append(self._component_for_section(section, session_id=session_id, probe=probe))
        report = build_operator_status_report(
            scope=resolved_scope,
            freshness="probed" if probe else "cached",
            components=tuple(components),
            snapshot_id=_snapshot_id(resolved_scope, components),
        )
        return {"ok": True, **operator_status_report_record(report)}

    def plan_operator_action(
        self,
        session_id: str,
        *,
        action: str,
        base_snapshot_id: str = "",
        parameters: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        resolved_action = _normalize_action(action)
        params = dict(parameters or {})
        snapshot_id = base_snapshot_id.strip() or self._action_snapshot(session_id, resolved_action)
        try:
            plan = self._build_action_plan(
                action=resolved_action,
                base_snapshot_id=snapshot_id,
                parameters=params,
            )
        except ValueError as error:
            return operator_error_envelope(
                code="invalid_operator_action",
                message=str(error),
                hint="Use skill.enable, skill.disable, provider.set_default, or daemon.restart.",
            )
        self._plans[plan.plan_id] = plan
        return {"ok": True, **operator_action_plan_record(plan)}

    def apply_operator_action(
        self,
        session_id: str,
        *,
        plan_id: str,
        confirmation_token: str = "",
        parameters: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        plan = self._plans.get(plan_id)
        if plan is None:
            return operator_error_envelope(
                code="plan_not_found",
                message=f"Operator plan was not found: {plan_id}",
                hint="Run phase=plan again before applying.",
            )
        if plan.expires_at is not None and datetime.now(timezone.utc) > plan.expires_at:
            self._plans.pop(plan_id, None)
            return operator_error_envelope(
                code="plan_expired",
                message=f"Operator plan expired: {plan_id}",
                hint="Inspect again and build a fresh plan.",
                retryable=True,
            )
        if not _confirmation_accepted(confirmation_token, plan):
            return operator_error_envelope(
                code="approval_required",
                message="Operator apply requires explicit confirmation.",
                hint="After the user confirms, pass confirmation_token=confirmed.",
            )
        current_snapshot_id = self._action_snapshot(session_id, plan.action)
        if plan.base_snapshot_id and current_snapshot_id != plan.base_snapshot_id:
            return operator_error_envelope(
                code="snapshot_conflict",
                message="Runtime state changed after the operator plan was created.",
                hint="Inspect again and rebuild the plan before applying.",
                retryable=True,
            )

        started = datetime.now(timezone.utc)
        params = {**dict(plan.parameters), **dict(parameters or {})}
        try:
            changes, verification, rollback_hint = self._apply_action(
                session_id=session_id,
                action=plan.action,
                parameters=params,
            )
        except Exception as error:
            finished = datetime.now(timezone.utc)
            receipt = OperatorActionReceipt(
                receipt_id=f"operator-receipt:{uuid4().hex[:12]}",
                plan_id=plan.plan_id,
                action=plan.action,
                result="failed",
                started_at=started,
                finished_at=finished,
                changes_applied=(),
                verification={"error": str(error)},
                rollback_hint="No rollback was applied because the action failed before completion.",
                redactions_applied=("secret-like keys",),
            )
            return {"ok": False, **operator_action_receipt_record(receipt)}

        finished = datetime.now(timezone.utc)
        receipt = OperatorActionReceipt(
            receipt_id=f"operator-receipt:{uuid4().hex[:12]}",
            plan_id=plan.plan_id,
            action=plan.action,
            result="applied",
            started_at=started,
            finished_at=finished,
            changes_applied=changes,
            verification=verification,
            rollback_hint=rollback_hint,
            redactions_applied=("secret-like keys",),
        )
        self._plans.pop(plan_id, None)
        return {"ok": True, **operator_action_receipt_record(receipt)}

    def _sections_for_scope(self, scope: str, include: tuple[str, ...]) -> tuple[str, ...]:
        base = {
            "summary": ("runtime", "provider", "daemon", "skills", "tools"),
            "all": ("runtime", "provider", "daemon", "skills", "tools", "security"),
            "runtime": ("runtime",),
            "provider": ("provider",),
            "daemon": ("daemon",),
            "skills": ("skills",),
            "tools": ("tools",),
            "security": ("security",),
        }.get(scope, ("runtime",))
        sections = list(base)
        for item in include:
            normalized = _normalize_scope(item)
            if normalized in {"runtime", "provider", "daemon", "skills", "tools", "security"} and normalized not in sections:
                sections.append(normalized)
        return tuple(sections)

    def _component_for_section(self, section: str, *, session_id: str, probe: bool) -> OperatorComponentStatus:
        if section == "provider":
            return self._provider_component(probe=probe)
        if section == "daemon":
            return self._daemon_component(probe=probe)
        if section == "skills":
            return self._skills_component(session_id=session_id)
        if section == "tools":
            return self._tools_component()
        if section == "security":
            return self._security_component()
        return OperatorComponentStatus(
            component="runtime",
            state="ok",
            summary=f"{self.surface_label} operator surface is configured.",
            details={"surface": self.surface_label},
        )

    def _provider_component(self, *, probe: bool) -> OperatorComponentStatus:
        if self.provider_summary is None:
            return _unavailable_component("provider", "Provider management is not configured.")
        summary = dict(self.provider_summary())
        details: dict[str, Any] = {"active_provider": summary}
        issues: list[OperatorDiagnosticIssue] = []
        if probe and self.provider_doctor is not None:
            doctor = dict(self.provider_doctor(True))
            details["doctor"] = doctor
            issues.extend(_provider_doctor_issues(doctor))
        state = _provider_state(summary, issues)
        return OperatorComponentStatus(
            component="provider",
            state=state,
            summary=_provider_summary_line(summary, state),
            details=details,
            issues=tuple(issues),
        )

    def _daemon_component(self, *, probe: bool) -> OperatorComponentStatus:
        if self.daemon_status is None:
            return _unavailable_component("daemon", "Daemon management is not configured.")
        details = dict(self.daemon_status(probe))
        running = bool(details.get("running"))
        status = str(details.get("status") or ("running" if running else "stopped"))
        state = "ok" if running else "stopped"
        issues = ()
        if not running:
            issues = (
                OperatorDiagnosticIssue(
                    code="daemon_stopped",
                    severity="warning",
                    message="Elephant daemon is not running.",
                    hint="Use operator action daemon.restart when the daemon should be running.",
                    evidence={"status": status},
                ),
            )
        return OperatorComponentStatus(
            component="daemon",
            state=state,
            summary=f"daemon status is {status}",
            details=details,
            issues=issues,
        )

    def _skills_component(self, *, session_id: str) -> OperatorComponentStatus:
        if self.skill_management is None:
            return _unavailable_component("skills", "Skill management is not configured.")
        entries = tuple(self.skill_management.list_skill_hub(limit=None))
        enabled = [entry for entry in entries if bool(entry.metadata.get("default_enabled", True))]
        operator_entry = next((entry for entry in entries if entry.skill_id == "elephant-operator"), None)
        details = {
            "total": len(entries),
            "enabled": len(enabled),
            "disabled": max(0, len(entries) - len(enabled)),
            "operator_skill": (
                {
                    "skill_id": operator_entry.skill_id,
                    "source_id": operator_entry.source_id,
                    "default_enabled": bool(operator_entry.metadata.get("default_enabled", True)),
                }
                if operator_entry is not None
                else None
            ),
        }
        issues: tuple[OperatorDiagnosticIssue, ...] = ()
        state = "ok"
        if operator_entry is None:
            state = "degraded"
            issues = (
                OperatorDiagnosticIssue(
                    code="operator_skill_missing",
                    severity="warning",
                    message="The elephant-operator skill is not present in the skill hub.",
                    hint="Refresh or reinstall built-in skills.",
                ),
            )
        return OperatorComponentStatus(
            component="skills",
            state=state,
            summary=f"{len(enabled)}/{len(entries)} skill entries enabled by default",
            details=details,
            issues=issues,
        )

    def _tools_component(self) -> OperatorComponentStatus:
        runtime = self.tool_runtime() if self.tool_runtime is not None else None
        if runtime is None:
            return _unavailable_component("tools", "Tool runtime is not configured.")
        all_tools = tuple(runtime.list_tools())
        model_tools = tuple(runtime.list_tools(audience="model", enabled_only=True))
        operator_tools = tuple(runtime.list_tools(audience="operator", enabled_only=True))
        unavailable = [
            {"tool_id": tool.tool_id, "reason": tool.availability.reason or "unavailable"}
            for tool in all_tools
            if not tool.available
        ]
        strict = [
            tool.tool_id
            for tool in all_tools
            if str(tool.side_effects.approval_class) == "strict"
        ]
        return OperatorComponentStatus(
            component="tools",
            state="ok",
            summary=f"{len(model_tools)} model-visible and {len(operator_tools)} operator-visible enabled tools",
            details={
                "registered": len(all_tools),
                "model_visible": [tool.tool_id for tool in model_tools],
                "operator_visible": [tool.tool_id for tool in operator_tools],
                "strict_approval": strict,
                "unavailable": unavailable,
            },
        )

    def _security_component(self) -> OperatorComponentStatus:
        policy = self.security_policy() if self.security_policy is not None else None
        details: dict[str, Any] = {"surface": self.surface_label}
        if policy is not None:
            rule_for = getattr(policy, "rule_for", None)
            if callable(rule_for):
                try:
                    from packages.security import ApprovalClass

                    details["approval_rules"] = {
                        approval.value: (
                            {
                                "rule_id": getattr(rule_for(approval), "rule_id", ""),
                                "decision": str(getattr(rule_for(approval), "default_decision", "")),
                                "risk": str(getattr(rule_for(approval), "risk_level", "")),
                            }
                            if rule_for(approval) is not None
                            else None
                        )
                        for approval in ApprovalClass
                    }
                except Exception:
                    details["approval_rules"] = "unavailable"
        return OperatorComponentStatus(
            component="security",
            state="ok",
            summary="operator actions are governed by tool visibility and approval policy",
            details=details,
        )

    def _build_action_plan(
        self,
        *,
        action: str,
        base_snapshot_id: str,
        parameters: Mapping[str, Any],
    ) -> OperatorActionPlan:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        if action in {"skill.enable", "skill.disable"}:
            skill_id = _required_param(parameters, "skill_id")
            verb = "enable" if action == "skill.enable" else "disable"
            return OperatorActionPlan(
                plan_id=f"operator-plan:{uuid4().hex[:12]}",
                action=action,
                base_snapshot_id=base_snapshot_id,
                required_approval="standard",
                expected_changes=(f"{verb} skill {skill_id}",),
                risks=("Changes which procedural context may be loaded in future turns.",),
                rollback=(f"Run skill.{'disable' if action == 'skill.enable' else 'enable'} for {skill_id}.",),
                expires_at=expires_at,
                parameters={"skill_id": skill_id},
            )
        if action == "provider.set_default":
            provider_id = _required_param(parameters, "provider_id")
            model_id = str(parameters.get("model_id") or parameters.get("default_model") or "").strip()
            label = f"set default provider to {provider_id}" + (f" / {model_id}" if model_id else "")
            return OperatorActionPlan(
                plan_id=f"operator-plan:{uuid4().hex[:12]}",
                action=action,
                base_snapshot_id=base_snapshot_id,
                required_approval="strict",
                expected_changes=(label,),
                risks=("Affects future model calls on this runtime surface.",),
                rollback=("Reapply the previous provider snapshot from the operator receipt or config history.",),
                expires_at=expires_at,
                parameters=dict(parameters),
            )
        if action == "daemon.restart":
            return OperatorActionPlan(
                plan_id=f"operator-plan:{uuid4().hex[:12]}",
                action=action,
                base_snapshot_id=base_snapshot_id,
                required_approval="strict",
                expected_changes=("restart the local Elephant daemon",),
                risks=("Temporarily interrupts gateway, cron, supervisor, and background worker services.",),
                rollback=("Restart again or stop the daemon if the service should remain down.",),
                expires_at=expires_at,
                parameters=dict(parameters),
            )
        raise ValueError(f"unsupported operator action: {action}")

    def _apply_action(
        self,
        *,
        session_id: str,
        action: str,
        parameters: Mapping[str, Any],
    ) -> tuple[tuple[str, ...], Mapping[str, Any], str]:
        if action in {"skill.enable", "skill.disable"}:
            if self.skill_management is None:
                raise RuntimeError("skill management is not configured")
            skill_id = _required_param(parameters, "skill_id")
            enabled = action == "skill.enable"
            updated = self.skill_management.set_skill_enabled(skill_id, enabled, session_id=session_id)
            verified = self.skill_management.inspect_skill(skill_id, session_id=session_id)
            verification = {
                "skill_id": getattr(verified, "skill_id", skill_id),
                "enabled": bool(getattr(verified, "enabled", enabled)),
                "updated_enabled": bool(getattr(updated, "enabled", enabled)),
            }
            return (
                (f"{'enabled' if enabled else 'disabled'} skill {skill_id}",),
                verification,
                f"Run skill.{'disable' if enabled else 'enable'} for {skill_id}.",
            )
        if action == "provider.set_default":
            if self.set_default_provider is None:
                raise RuntimeError("provider mutation is not configured")
            result = dict(self.set_default_provider(parameters))
            verification = {
                "provider": dict(self.provider_summary()) if self.provider_summary is not None else result,
                "result": result,
            }
            provider_id = str(parameters.get("provider_id") or parameters.get("providerId") or "").strip()
            return (
                (f"set default provider to {provider_id or '<unknown>'}",),
                verification,
                "Reapply the previous provider settings if this provider should not remain active.",
            )
        if action == "daemon.restart":
            if self.daemon_restart is None:
                raise RuntimeError("daemon mutation is not configured")
            result = dict(self.daemon_restart(parameters))
            verification = {
                "restart": result,
                "daemon": dict(self.daemon_status(True)) if self.daemon_status is not None else {},
            }
            return (
                ("restarted Elephant daemon",),
                verification,
                "Run daemon.restart again or stop the daemon if the restart was unintended.",
            )
        raise ValueError(f"unsupported operator action: {action}")

    def _action_snapshot(self, session_id: str, action: str) -> str:
        scope = {
            "skill.enable": "skills",
            "skill.disable": "skills",
            "provider.set_default": "provider",
            "daemon.restart": "daemon",
        }.get(action, "summary")
        report = self.inspect_operator(session_id, scope=scope, probe=False)
        return str(report.get("snapshotId") or "")


def _normalize_scope(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized if normalized in {"summary", "runtime", "provider", "daemon", "skills", "tools", "security", "all"} else "summary"


def _normalize_action(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", ".").replace("-", ".")
    aliases = {
        "skill.enable": "skill.enable",
        "skill.disable": "skill.disable",
        "skills.enable": "skill.enable",
        "skills.disable": "skill.disable",
        "enable.skill": "skill.enable",
        "disable.skill": "skill.disable",
        "provider.set.default": "provider.set_default",
        "provider.default.update": "provider.set_default",
        "provider.update": "provider.set_default",
        "set.default.provider": "provider.set_default",
        "daemon.restart": "daemon.restart",
        "restart.daemon": "daemon.restart",
    }
    return aliases.get(normalized, normalized)


def _required_param(parameters: Mapping[str, Any], name: str) -> str:
    value = str(parameters.get(name) or parameters.get(_camel_case(name)) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _confirmation_accepted(value: str, plan: OperatorActionPlan) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"confirmed", "confirm", "approved", "approve", plan.plan_id.lower()}


def _snapshot_id(scope: str, components: list[OperatorComponentStatus]) -> str:
    payload = {
        "scope": scope,
        "components": [
            {
                "component": component.component,
                "state": component.state,
                "summary": component.summary,
                "details": redact_operator_value(component.details),
                "issues": [
                    {
                        "code": issue.code,
                        "severity": issue.severity,
                        "message": issue.message,
                        "hint": issue.hint,
                        "repair_action_id": issue.repair_action_id,
                        "evidence": redact_operator_value(issue.evidence),
                    }
                    for issue in component.issues
                ],
            }
            for component in components
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return f"operator-snapshot:{hashlib.sha256(encoded).hexdigest()[:16]}"


def _unavailable_component(component: str, message: str) -> OperatorComponentStatus:
    return OperatorComponentStatus(
        component=component,
        state="unknown",
        summary=message,
        issues=(
            OperatorDiagnosticIssue(
                code=f"{component}_unavailable",
                severity="warning",
                message=message,
            ),
        ),
    )


def _provider_state(summary: Mapping[str, Any], issues: list[OperatorDiagnosticIssue]) -> str:
    if any(issue.severity == "error" for issue in issues):
        return "misconfigured"
    if summary.get("source") != "configured":
        return "degraded"
    if summary.get("secret_status") == "missing":
        return "misconfigured"
    return "ok"


def _provider_summary_line(summary: Mapping[str, Any], state: str) -> str:
    provider_id = str(summary.get("provider_id") or summary.get("providerId") or "unknown")
    model_id = str(summary.get("model_id") or summary.get("default_model") or summary.get("modelId") or "")
    suffix = f" using {model_id}" if model_id else ""
    return f"provider {provider_id}{suffix} is {state}"


def _provider_doctor_issues(doctor: Mapping[str, Any]) -> list[OperatorDiagnosticIssue]:
    issues: list[OperatorDiagnosticIssue] = []
    for check in doctor.get("checks", ()):
        if not isinstance(check, Mapping):
            continue
        status = str(check.get("status") or "").strip().lower()
        if status in {"ok", "ready", "configured", "available", "external", "hinted"}:
            continue
        issues.append(
            OperatorDiagnosticIssue(
                code=f"provider_{check.get('check') or 'check'}_{status or 'unknown'}",
                severity="error" if status in {"missing", "not-ready", "failed"} else "warning",
                message=str(check.get("summary") or f"Provider check {check.get('check')} is {status or 'unknown'}."),
                hint="Run provider setup or adjust the default provider configuration.",
                evidence=dict(check),
            )
        )
    return issues


__all__ = ["OperatorRuntimeManagementSurface"]
