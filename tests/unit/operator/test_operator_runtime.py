from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.operator import (
    OperatorActionPlan,
    OperatorActionReceipt,
    OperatorComponentStatus,
    OperatorDiagnosticIssue,
    OperatorRuntimeManagementSurface,
    build_operator_status_report,
    operator_action_plan_record,
    operator_action_receipt_record,
    operator_error_envelope,
    operator_status_report_record,
    redact_operator_value,
)


class _SkillEntry:
    def __init__(self, skill_id: str, *, enabled: bool = True) -> None:
        self.skill_id = skill_id
        self.display_name = skill_id
        self.summary = ""
        self.source_id = "builtin"
        self.source_label = "Built In"
        self.metadata = {"default_enabled": enabled}


class _SkillDefinition:
    def __init__(self, skill_id: str, *, enabled: bool = True) -> None:
        self.skill_id = skill_id
        self.enabled = enabled


class _SkillSurface:
    def __init__(self) -> None:
        self.enabled = {"elephant-operator": True, "workspace-search": True}

    def list_skill_hub(self, *, limit=None):  # type: ignore[no-untyped-def]
        entries = tuple(_SkillEntry(skill_id, enabled=enabled) for skill_id, enabled in self.enabled.items())
        if limit is None:
            return entries
        return entries[:limit]

    def set_skill_enabled(self, skill_id: str, enabled: bool, **_kwargs):  # type: ignore[no-untyped-def]
        self.enabled[skill_id] = enabled
        return _SkillDefinition(skill_id, enabled=enabled)

    def inspect_skill(self, skill_id: str, **_kwargs):  # type: ignore[no-untyped-def]
        return _SkillDefinition(skill_id, enabled=self.enabled[skill_id])


class _ToolRuntime:
    def __init__(self, tools) -> None:  # type: ignore[no-untyped-def]
        self._tools = tuple(tools)

    def list_tools(self, *, audience=None, enabled_only=False, available_only=False):  # type: ignore[no-untyped-def]
        tools = self._tools
        if audience is not None:
            tools = tuple(tool for tool in tools if tool.visible_to(audience))
        if enabled_only:
            tools = tuple(tool for tool in tools if tool.enabled)
        if available_only:
            tools = tuple(tool for tool in tools if tool.available)
        return tools


class OperatorRuntimeTest(unittest.TestCase):
    def test_status_report_rolls_up_component_state_and_redacts_secrets(self) -> None:
        report = build_operator_status_report(
            scope="provider",
            freshness="probed",
            generated_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
            components=(
                OperatorComponentStatus(
                    component="provider",
                    state="misconfigured",
                    summary="provider credentials are missing",
                    details={"provider_id": "openai", "api_key": "sk-live"},
                    issues=(
                        OperatorDiagnosticIssue(
                            code="provider_secret_missing",
                            severity="error",
                            message="Provider API key is not configured.",
                            hint="Configure a provider secret before deep model probes.",
                            evidence={"token": "raw-token"},
                        ),
                    ),
                ),
            ),
        )

        record = operator_status_report_record(report)

        self.assertEqual(record["status"], "misconfigured")
        self.assertEqual(record["freshness"], "probed")
        self.assertEqual(record["components"][0]["details"]["api_key"], "<redacted>")
        self.assertEqual(record["components"][0]["issues"][0]["evidence"]["token"], "<redacted>")

    def test_action_plan_and_receipt_records_are_structured_and_redacted(self) -> None:
        plan = OperatorActionPlan(
            plan_id="operator-plan:1",
            action="provider_default_update",
            base_snapshot_id="operator-snapshot:1",
            required_approval="strict",
            expected_changes=("update default provider",),
            risks=("affects future sessions",),
            rollback=("restore prior provider snapshot",),
            parameters={"model_id": "gpt-test", "apiToken": "secret"},
        )
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
        receipt = OperatorActionReceipt(
            receipt_id="operator-receipt:1",
            plan_id=plan.plan_id,
            action=plan.action,
            result="applied",
            started_at=now,
            finished_at=now,
            changes_applied=("updated provider",),
            verification={"status": "ok", "password": "secret"},
            rollback_hint="Reapply the previous provider snapshot.",
            redactions_applied=("secret-like keys",),
        )

        plan_record = operator_action_plan_record(plan)
        receipt_record = operator_action_receipt_record(receipt)

        self.assertEqual(plan_record["requiredApproval"], "strict")
        self.assertEqual(plan_record["parameters"]["apiToken"], "<redacted>")
        self.assertEqual(receipt_record["result"], "applied")
        self.assertEqual(receipt_record["verification"]["password"], "<redacted>")

    def test_error_envelope_and_nested_redaction_are_stable(self) -> None:
        envelope = operator_error_envelope(
            code="snapshot_conflict",
            message="The runtime changed after the plan was created.",
            hint="Inspect again and rebuild the plan.",
            retryable=True,
        )
        redacted = redact_operator_value({"nested": [{"secret": "x"}, {"safe": "y"}]})

        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "snapshot_conflict")
        self.assertTrue(envelope["error"]["retryable"])
        self.assertEqual(redacted["nested"][0]["secret"], "<redacted>")
        self.assertEqual(redacted["nested"][1]["safe"], "y")

    def test_management_surface_inspects_and_redacts_runtime_components(self) -> None:
        from packages.tools import ToolDefinition, ToolSideEffectMetadata

        surface = OperatorRuntimeManagementSurface(
            surface_label="test",
            provider_summary=lambda: {
                "provider_id": "openai",
                "model_id": "gpt-test",
                "source": "configured",
                "secret_status": "stored",
                "api_key": "sk-test",
            },
            daemon_status=lambda _probe: {"running": False, "status": "stopped", "pid": None},
            skill_management=_SkillSurface(),
            tool_runtime=lambda: _ToolRuntime(
                (
                    ToolDefinition(
                        tool_id="tool.operator.inspect",
                        display_name="Operator Inspect",
                        version="1",
                        audience="both",
                        side_effects=ToolSideEffectMetadata(reads_state=True),
                    ),
                )
            ),
        )

        report = surface.inspect_operator("session-1", scope="all")

        self.assertTrue(report["ok"])
        self.assertTrue(str(report["snapshotId"]).startswith("operator-snapshot:"))
        provider = next(component for component in report["components"] if component["component"] == "provider")
        self.assertEqual(provider["details"]["active_provider"]["api_key"], "<redacted>")
        daemon = next(component for component in report["components"] if component["component"] == "daemon")
        self.assertEqual(daemon["state"], "stopped")

    def test_management_surface_plans_and_applies_skill_toggle(self) -> None:
        skills = _SkillSurface()
        surface = OperatorRuntimeManagementSurface(
            surface_label="test",
            skill_management=skills,
        )

        plan = surface.plan_operator_action(
            "session-1",
            action="skill.disable",
            parameters={"skill_id": "workspace-search"},
        )
        blocked = surface.apply_operator_action(
            "session-1",
            plan_id=str(plan["planId"]),
            confirmation_token="",
        )
        receipt = surface.apply_operator_action(
            "session-1",
            plan_id=str(plan["planId"]),
            confirmation_token="confirmed",
        )

        self.assertEqual(plan["requiredApproval"], "standard")
        self.assertEqual(blocked["error"]["code"], "approval_required")
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["verification"]["enabled"], False)
        self.assertFalse(skills.enabled["workspace-search"])

    def test_management_surface_applies_provider_and_daemon_mutations(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []
        daemon_running = {"value": False}

        def _provider_set(parameters):  # type: ignore[no-untyped-def]
            calls.append(("provider", dict(parameters)))
            return {"active_provider": {"provider_id": parameters["provider_id"]}}

        def _daemon_restart(parameters):  # type: ignore[no-untyped-def]
            calls.append(("daemon", dict(parameters)))
            daemon_running["value"] = True
            return {"status": "ok"}

        surface = OperatorRuntimeManagementSurface(
            surface_label="test",
            provider_summary=lambda: {"provider_id": "preview", "source": "preview", "secret_status": "not-required"},
            set_default_provider=_provider_set,
            daemon_status=lambda _probe: {"running": daemon_running["value"], "status": "running" if daemon_running["value"] else "stopped"},
            daemon_restart=_daemon_restart,
        )

        provider_plan = surface.plan_operator_action(
            "session-1",
            action="provider.set_default",
            parameters={"provider_id": "openai", "model_id": "gpt-test"},
        )
        provider_receipt = surface.apply_operator_action(
            "session-1",
            plan_id=str(provider_plan["planId"]),
            confirmation_token="confirmed",
        )
        daemon_plan = surface.plan_operator_action("session-1", action="daemon.restart")
        daemon_receipt = surface.apply_operator_action(
            "session-1",
            plan_id=str(daemon_plan["planId"]),
            confirmation_token="confirmed",
        )

        self.assertTrue(provider_receipt["ok"])
        self.assertTrue(daemon_receipt["ok"])
        self.assertEqual(calls[0][0], "provider")
        self.assertEqual(calls[1][0], "daemon")


if __name__ == "__main__":
    unittest.main()
