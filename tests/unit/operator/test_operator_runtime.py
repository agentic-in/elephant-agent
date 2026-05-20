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
    build_operator_status_report,
    operator_action_plan_record,
    operator_action_receipt_record,
    operator_error_envelope,
    operator_status_report_record,
    redact_operator_value,
)


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


if __name__ == "__main__":
    unittest.main()
