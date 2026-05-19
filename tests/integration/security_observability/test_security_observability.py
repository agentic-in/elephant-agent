from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from apps.cli.runtime import CliRuntime
from apps.gateway import build_gateway_app
from packages.auth import AuthProfile, ProfileCredentialResolver, SecretReference
from packages.security import (
    ApprovalClass,
    PolicyDecision,
    RiskLevel,
    SecurityPolicy,
    SecurityRequest,
    SecurityAuditEvent,
    evaluate_with_telemetry,
)


class _CaptureSink:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def emit(self, event: dict[str, object]) -> None:
        self.records.append(dict(event))


class _MissingSecretStore:
    def resolve(self, reference: SecretReference):
        raise LookupError(f"missing secret reference: {reference.reference_id}")

    def read(self, reference: SecretReference) -> str:
        raise LookupError(f"missing secret reference: {reference.reference_id}")


class SecurityObservabilityIntegrationTests(unittest.TestCase):
    def test_approval_path_emits_requested_classified_decided_and_granted(self) -> None:
        sink = _CaptureSink()
        policy = SecurityPolicy.default()
        request = SecurityRequest(
            request_id="req-approval",
            approval_class=ApprovalClass.WRITE,
            operation="persist-artifact",
            episode_id="episode-1",
            consent_given=True,
        )

        result = evaluate_with_telemetry(policy, request, sink)

        self.assertEqual(result.request_id, "req-approval")
        self.assertEqual(
            [record["name"] for record in sink.records],
            [
                "approval.requested",
                "approval.classified",
                "approval.decided",
                "approval.granted",
            ],
        )
        self.assertTrue(all(record["episode_id"] == "episode-1" for record in sink.records[:3]))
        self.assertEqual(sink.records[0]["family"], "approval")
        self.assertEqual(sink.records[2]["decision"], "approved")
        self.assertEqual(sink.records[3]["decision"], "approved")
        self.assertEqual(sink.records[3]["policy_id"], "write-default")

    def test_missing_policy_rule_emits_failure_trace(self) -> None:
        sink = _CaptureSink()
        policy = SecurityPolicy(rules={})
        request = SecurityRequest(
            request_id="req-missing",
            approval_class=ApprovalClass.EXEC,
            operation="run-shell-command",
            episode_id="episode-2",
        )

        result = evaluate_with_telemetry(policy, request, sink)

        self.assertEqual(result.rule_id, "unregistered-surface")
        self.assertEqual(result.decision.value, "deny")
        self.assertEqual(
            [record["name"] for record in sink.records],
            [
                "approval.requested",
                "approval.classified",
                "approval.decided",
                "approval.denied",
                "failure.side_effect.reported",
            ],
        )
        failure = sink.records[-1]
        self.assertEqual(failure["family"], "failure")
        self.assertEqual(failure["error_kind"], "approval_context_missing")
        self.assertEqual(failure["severity"], "critical")
        self.assertEqual(failure["operation"], "run-shell-command")
        self.assertEqual(failure["detail"]["rule_id"], "unregistered-surface")

    def test_missing_secret_resolution_is_actionable_and_redacted(self) -> None:
        resolver = ProfileCredentialResolver(_MissingSecretStore())
        profile = AuthProfile(
            profile_id="provider-openrouter",
            provider_id="openrouter",
            secret_references=(
                SecretReference(
                    reference_id="secret-openrouter-api-key",
                    provider_id="openrouter",
                    secret_name="api_token",
                    secret_key="api_key",
                ),
            ),
        )

        with self.assertRaises(LookupError) as context:
            resolver.resolve(profile)

        message = str(context.exception)
        self.assertIn("missing runtime secret for provider 'openrouter' key 'api_key'", message)
        self.assertIn("elephant init", message)
        self.assertIn("/providers", message)
        self.assertIn("elephant status", message)
        self.assertNotIn("sk-live-123", message)

    def test_auth_profile_rejects_inline_secret_material(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "extra_headers entry 'Authorization' must not carry provider credentials",
        ):
            AuthProfile(
                profile_id="provider-inline-header",
                provider_id="openai-compatible",
                extra_headers={"Authorization": "Bearer sk-live-123"},
            )

        with self.assertRaisesRegex(
            ValueError,
            "secret reference metadata entry 'token' must reference a secret source",
        ):
            SecretReference(
                reference_id="secret-inline-token",
                provider_id="openai-compatible",
                secret_name="api_token",
                secret_key="api_key",
                metadata={"token": "sk-live-123"},
            )

    def test_security_records_redact_secret_like_metadata_and_support_details(
        self,
    ) -> None:
        sink = _CaptureSink()
        policy = SecurityPolicy(rules={})
        request = SecurityRequest(
            request_id="req-redacted",
            approval_class=ApprovalClass.NETWORK,
            operation="POST https://api.example.invalid/v1?api_key=sk-live-123",
            episode_id="episode-redacted",
            description="Authorization: Bearer sk-live-123",
            metadata={
                "authorization": "Bearer sk-live-123",
                "note": "token=sk-live-123",
                "provider": "openrouter",
            },
        )

        result = evaluate_with_telemetry(policy, request, sink)

        self.assertEqual(result.decision, PolicyDecision.DENY)
        requested = sink.records[0]
        failure = sink.records[-1]
        self.assertEqual(requested["reason"], "Authorization: ***")
        self.assertEqual(requested["detail"]["metadata"]["authorization"], "***")
        self.assertEqual(requested["detail"]["metadata"]["note"], "token=***")
        self.assertEqual(failure["operation"], "POST https://api.example.invalid/v1?api_key=***")
        serialized = json.dumps(sink.records, sort_keys=True)
        self.assertNotIn("sk-live-123", serialized)

    def test_security_audit_record_redacts_secret_like_summary(self) -> None:
        record = SecurityAuditEvent(
            event_id="audit:req-secret",
            request_id="req-secret",
            approval_class=ApprovalClass.NETWORK,
            decision=PolicyDecision.REVIEW,
            risk_level=RiskLevel.HIGH,
            summary="Authorization: Bearer sk-live-123",
            required_controls=("explicit-approval",),
            audit_tags=("network",),
        ).to_record()

        self.assertEqual(record["summary"], "Authorization: ***")
        self.assertEqual(record["required_controls"], ("explicit-approval",))
        self.assertEqual(record["audit_tags"], ("network",))

    def test_cli_mutation_paths_emit_security_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            profile_dir = root / "profile"
            profile_dir.mkdir()
            (root / "profile.json").write_text(
                json.dumps(
                    {
                        "profile_id": "profile-companion",
                        "display_name": "Elephant Agent",
                        "mode": "companion",
                    }
                ),
                encoding="utf-8",
            )
            runtime = CliRuntime.create(state_dir=state_dir)
            runtime.start()
            runtime.update_identity_state(
                profile_id=runtime.current_profile().state.profile_id,
                elephant_identity_text="Stay direct and safe.",
            )

            snapshot = json.loads(runtime.snapshot_path.read_text(encoding="utf-8"))

        telemetry = [record for record in snapshot.get("telemetry", ()) if record.get("source") == "cli.operator"]
        self.assertGreaterEqual(len(telemetry), 2)
        self.assertEqual(telemetry[0]["name"], "approval.requested")
        self.assertIn(telemetry[-1]["name"], {"approval.granted", "approval.denied"})
        serialized = json.dumps(telemetry, sort_keys=True)
        self.assertIn("cli.identity.surface.update", serialized)
        self.assertNotIn("Stay direct and safe.", serialized)

    def test_gateway_delivery_emits_policy_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            profile_dir = root / "profile"
            state_dir = root / "state"
            profile_dir.mkdir()
            state_dir.mkdir()
            (root / "profile.json").write_text(
                json.dumps(
                    {
                        "profile_id": "profile:operator",
                        "display_name": "Operator",
                        "mode": "companion",
                    }
                ),
                encoding="utf-8",
            )
            app, chat_adapter, _ = build_gateway_app(state_dir=state_dir)

            exchange = chat_adapter.receive_text(
                conversation_id="chat-1",
                external_user_id="user-1",
                body="hello",
                display_name="Ada",
                event_id="evt-1",
            )

        self.assertEqual(exchange.delivery.policy_result.decision, PolicyDecision.ALLOW)
        security_events = [record for record in app.telemetry.events if record.get("source") == "gateway.messaging"]
        self.assertGreaterEqual(len(security_events), 4)
        self.assertEqual(security_events[0]["name"], "approval.requested")
        self.assertEqual(security_events[-1]["name"], "approval.granted")

    def test_security_doctor_surfaces_redacted_support_bundle_and_policy_bundles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            profile_dir = root / "profile"
            profile_dir.mkdir()
            (root / "profile.json").write_text(
                json.dumps(
                    {
                        "profile_id": "profile-companion",
                        "display_name": "Elephant Agent",
                        "mode": "companion",
                    }
                ),
                encoding="utf-8",
            )
            runtime = CliRuntime.create(state_dir=state_dir)
            runtime.set_default_provider(
                provider_id="openai-compatible",
                base_url="https://api.example.invalid/v1",
                model_id="tke/demo",
                api_key="sk-live-123",
                context_window_tokens=128000,
                context_window_mode="auto",
            )
            runtime.set_openai_compatible_embedding_provider(
                base_url="https://api.example.invalid/v1",
                model_id="text-embedding-3-large",
                dimensions=1536,
                api_key="sk-embedding-live",
            )
            report = runtime.security_doctor()

        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["support_bundle"]["provider"]["provider_id"], "openai-compatible")
        self.assertTrue(report["support_bundle"]["provider"]["secret_reference_ids"])
        self.assertEqual(
            report["support_bundle"]["provider"]["stored_secret_reference_ids"],
            report["support_bundle"]["provider"]["secret_reference_ids"],
        )
        self.assertEqual(
            report["support_bundle"]["provider"]["secret_store"],
            "encrypted-local-store",
        )
        self.assertEqual(
            report["support_bundle"]["embedding_provider"]["provider_id"],
            "openai-compatible-embed",
        )
        self.assertTrue(report["support_bundle"]["embedding_provider"]["secret_reference_ids"])
        self.assertEqual(
            report["support_bundle"]["embedding_provider"]["stored_secret_reference_ids"],
            report["support_bundle"]["embedding_provider"]["secret_reference_ids"],
        )
        self.assertEqual(
            tuple(bundle["surface_id"] for bundle in report["surface_bundles"]),
            ("cli.operator", "gateway.messaging", "deploy.support"),
        )
        serialized = json.dumps(report, sort_keys=True)
        self.assertNotIn("sk-live-123", serialized)
        self.assertNotIn("sk-embedding-live", serialized)
        self.assertIn("encrypted-local-store", serialized)

    def test_security_doctor_warns_when_provider_secrets_are_not_stored(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            profile_dir = root / "profile"
            profile_dir.mkdir()
            (root / "profile.json").write_text(
                json.dumps(
                    {
                        "profile_id": "profile-companion",
                        "display_name": "Elephant Agent",
                        "mode": "companion",
                        "provider_profile": {
                            "profile_id": "provider-openai-compatible",
                            "provider_id": "openai-compatible",
                            "base_url": "https://api.example.invalid/v1",
                            "default_model": "tke/demo",
                            "secret_references": [
                                {
                                    "reference_id": "secret-openai-compatible-api-key",
                                    "provider_id": "openai-compatible",
                                    "secret_name": "api_token",
                                    "secret_key": "api_key",
                                    "metadata": {},
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            runtime = CliRuntime.create(state_dir=state_dir)
            runtime.repository.upsert_auth_profile(
                AuthProfile(
                    profile_id="provider-embedding-openai-compatible",
                    provider_id="openai-compatible-embed",
                    transport_id="openai-compatible",
                    base_url="https://api.example.invalid/v1",
                    default_model="text-embedding-3-large",
                    auth_method="api_key",
                    provider_kind="embedding",
                    secret_references=(
                        SecretReference(
                            reference_id="secret-embedding-provider-openai-compatible-active-api-key",
                            provider_id="openai-compatible-embed",
                            secret_name="api_token",
                            secret_key="api_key",
                            metadata={
                                "storage": "local-vault",
                                "scope": "embedding-provider",
                            },
                        ),
                    ),
                    metadata={"embedding_active": "true", "dimensions": "1536"},
                )
            )
            report = runtime.security_doctor()

        self.assertEqual(report["status"], "not-ready")
        boundary_check = next(check for check in report["checks"] if check["check"] == "secret_boundary")
        self.assertEqual(boundary_check["status"], "warning")
        self.assertIn("missing stored provider secrets", str(boundary_check["summary"]))
        self.assertIn(
            "secret-embedding-provider-openai-compatible-active-api-key",
            str(boundary_check["summary"]),
        )


if __name__ == "__main__":
    unittest.main()
