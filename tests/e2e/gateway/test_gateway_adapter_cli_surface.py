from __future__ import annotations

from contextlib import redirect_stdout
import io
from types import SimpleNamespace
import unittest

from apps.gateway.runtime_capabilities import GatewayRecallCapability
import apps.gateway.__main__ as gateway_main
from apps.gateway.__main__ import command_main
from packages.contracts.runtime import EvidenceRetrievalRequest
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterCliSurfaceE2ETests(GatewayAdapterTestBase):
    def test_gateway_recall_capability_accepts_episode_scope(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeRecallRuntime:
            def retrieve_evidence(self, request):
                calls.append({"evidence_request": request})
                return SimpleNamespace(
                    candidates=(SimpleNamespace(recall="personal-recall"),),
                    scope_episode_ids=request.lineage_episode_ids,
                    scope_reason=request.scope_reason,
                )

        capability = GatewayRecallCapability(FakeRecallRuntime())

        evidence_request = EvidenceRetrievalRequest(
            episode_id="session-active",
            personal_model_id="personal-model:zoey",
            elephant_id="zoey",
            lineage_episode_ids=("session-active",),
            query="what does the user prefer",
            scopes=("episode", "elephant", "personal_model"),
            scope_reason="gateway personal recall",
        )
        retrieval = capability.retrieve_evidence(evidence_request)
        self.assertEqual(retrieval.candidates[0].recall, "personal-recall")
        self.assertEqual(
            calls[0]["evidence_request"].scopes,
            ("episode", "elephant", "personal_model"),
        )
        self.assertEqual(calls[0]["evidence_request"].personal_model_id, "personal-model:zoey")

    def test_gateway_help_omits_hidden_top_level_aliases(self) -> None:
        output = io.StringIO()
        with self.assertRaises(SystemExit) as exit_info, redirect_stdout(output):
            command_main(
                ["-h"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_info.exception.code, 0)
        rendered = output.getvalue()
        self.assertNotIn("==SUPPRESS==", rendered)
        self.assertIn("{setup,status,doctor,describe,feishu,discord,dingding,weixin,wecom}", rendered)
        self.assertNotIn("\n    serve", rendered)
        self.assertNotIn("\n    add", rendered)

    def test_gateway_module_has_no_legacy_top_level_parser(self) -> None:
        self.assertFalse(hasattr(gateway_main, "legacy_main"))
        self.assertFalse(hasattr(gateway_main, "_build_legacy_parser"))

    def test_gateway_provider_help_shows_public_describe_commands(self) -> None:
        for provider, expected_help in (
            ("feishu", "Print resolved Feishu account wiring as JSON."),
            ("discord", "Print resolved Discord account wiring as JSON."),
        ):
            output = io.StringIO()
            with self.assertRaises(SystemExit) as exit_info, redirect_stdout(output):
                command_main(
                    [provider, "-h"],
                    default_state_dir=self.state_dir,
                    default_control_state_dir=self.state_dir,
                )

            self.assertEqual(exit_info.exception.code, 0)
            rendered = output.getvalue()
            self.assertNotIn("==SUPPRESS==", rendered)
            self.assertIn(expected_help, rendered)


if __name__ == "__main__":
    unittest.main()
