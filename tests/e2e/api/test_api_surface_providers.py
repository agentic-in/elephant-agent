from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api import create_app
from packages.runtime_config import global_config_path_for_state_dir, load_global_config
from tests.e2e.api.api_surface_test_base import (
    APISurfaceTestBase,
    EMBEDDING_BOOTSTRAP_STATUSES,
)


class APISurfaceProviderE2ETest(APISurfaceTestBase):
    def test_openai_provider_profile_uses_first_party_runtime_resolution(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-openai",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "provider_profile": self._provider_profile(
                        profile_id="provider-openai",
                        provider_id="openai",
                        base_url=self.stub.openai_base_url,
                        default_model=None,
                        reference_id="secret-openai-token",
                        env_var="ELEPHANT_OPENAI_API_KEY",
                    ),
                    "episode_id": "session-openai",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)

        turn = self.app.dispatch(
            "POST",
            "/v1/episodes/session-openai/loops",
            body=self._body({"prompt": "Summarize the next release step."}),
        )
        self.assertEqual(turn.status_code, 200)
        self.assertTrue(
            turn.payload["outcome"]["execution"]["summary"].startswith(
                "live-response:Summarize the next release step."
            )
        )
        self.assertIn("transport=openai_responses", turn.payload["outcome"]["execution"]["side_effects"])
        self.assertIn("credential_keys=api_key", turn.payload["outcome"]["execution"]["side_effects"])
        self.assertEqual(turn.payload["inspection"]["provider_profile"]["provider_id"], "openai")

    def test_anthropic_provider_profile_uses_native_messages_runtime(self) -> None:
        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-anthropic",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "provider_profile": self._provider_profile(
                        profile_id="provider-anthropic",
                        provider_id="anthropic",
                        base_url=self.stub.anthropic_base_url,
                        default_model=None,
                        reference_id="secret-anthropic-token",
                        env_var="ELEPHANT_ANTHROPIC_API_KEY",
                    ),
                    "episode_id": "session-anthropic",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)

        turn = self.app.dispatch(
            "POST",
            "/v1/episodes/session-anthropic/loops",
            body=self._body({"prompt": "Explain the provider boundary."}),
        )
        self.assertEqual(turn.status_code, 200)
        self.assertEqual(
            turn.payload["outcome"]["execution"]["summary"],
            "live-anthropic:Explain the provider boundary.",
        )
        self.assertIn("transport=anthropic_messages", turn.payload["outcome"]["execution"]["side_effects"])
        self.assertIn("credential_keys=api_key", turn.payload["outcome"]["execution"]["side_effects"])
        self.assertEqual(turn.payload["inspection"]["provider_profile"]["transport_id"], "anthropic_messages")

    def test_provider_onboarding_and_default_provider_flow(self) -> None:
        provider_profile = self._provider_profile(
            profile_id="provider-openrouter",
            base_url=self.stub.openai_base_url,
            reference_id="secret-openrouter-token",
            extra_headers={"x-tenant": "elephant"},
        )

        listed = self.app.dispatch("GET", "/v1/providers")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.payload["active_provider"]["provider_id"], "preview")
        self.assertTrue(any(item["provider_id"] == "openai-compatible" for item in listed.payload["providers"]))

        setup = self.app.dispatch("GET", "/v1/providers/setup/openai-compatible")
        self.assertEqual(setup.status_code, 200)
        self.assertIn("base_url", setup.payload["guide"]["required_config_keys"])
        self.assertIn("model_id", setup.payload["guide"]["required_config_keys"])

        models = self.app.dispatch(
            "POST",
            "/v1/providers/models",
            body=self._body({"providerId": "openai-compatible", "baseUrl": self.stub.openai_base_url}),
        )
        self.assertEqual(models.status_code, 200)
        self.assertEqual(models.payload["providerId"], "openai-compatible")
        self.assertIn("openai/gpt-4o-mini", [model["model_id"] for model in models.payload["models"]])

        defaulted = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body({"provider_profile": provider_profile}),
        )
        self.assertEqual(defaulted.status_code, 200)
        self.assertEqual(defaulted.payload["provider_profile"]["provider_id"], "openai-compatible")
        self.assertEqual(defaulted.payload["provider_profile"]["base_url"], self.stub.openai_base_url)
        self.assertEqual(defaulted.payload["active_provider"]["provider_id"], "openai-compatible")
        self.assertEqual(defaulted.payload["active_provider"]["model_id"], "openai/gpt-4o-mini")
        self.assertEqual(defaulted.payload["active_provider"]["context_window_tokens"], 128000)
        self.assertEqual(defaulted.payload["active_provider"]["context_window_mode"], "auto")
        self.assertEqual(self.app.context_runtime.total_tokens, 128000)
        self.assertEqual(self.app.context.runtime.total_tokens, 128000)
        self.assertIn(defaulted.payload["active_provider"]["embedding_bootstrap_status"], EMBEDDING_BOOTSTRAP_STATUSES)
        config = load_global_config(
            global_config_path_for_state_dir(self.app.repository.database_path.parent),
            state_dir=self.app.repository.database_path.parent,
        )
        provider_config = config["models"]["provider"]
        self.assertEqual(
            provider_config["provider_id"],
            "openai-compatible",
        )
        self.assertEqual(
            provider_config["default_model"],
            "openai/gpt-4o-mini",
        )
        self.assertEqual(
            provider_config["metadata"]["context_window_tokens"],
            128000,
        )
        reloaded_app = create_app(
            database_path=self.app.repository.database_path,
            install_root=Path(self.tempdir.name),
        )
        self.assertEqual(reloaded_app.context_runtime.total_tokens, 128000)

        keys = self.app.dispatch("GET", "/v1/providers/keys")
        self.assertEqual(keys.status_code, 200)
        self.assertTrue(any(key["referenceId"] == "secret-openrouter-token" for key in keys.payload["keys"]))
        saved_key = self.app.dispatch(
            "PATCH",
            "/v1/providers/keys/secret-openrouter-token",
            body=self._body({"value": "sk-updated-provider-key"}),
        )
        self.assertEqual(saved_key.status_code, 200)
        self.assertTrue(saved_key.payload["hasValue"])

        initial_embedding = self.app.dispatch("GET", "/v1/providers/embeddings")
        self.assertEqual(initial_embedding.status_code, 200)
        self.assertEqual(initial_embedding.payload["embedding_provider"]["source"], "local-default")
        external_embedding = self.app.dispatch(
            "POST",
            "/v1/providers/embeddings",
            body=self._body(
                {
                    "source": "openai-compatible",
                    "baseUrl": self.stub.openai_base_url,
                    "modelId": "text-embedding-3-large",
                    "dimensions": 1536,
                    "apiKey": "sk-embedding-test",
                }
            ),
        )
        self.assertEqual(external_embedding.status_code, 200)
        self.assertEqual(external_embedding.payload["embedding_provider"]["source"], "configured")
        self.assertEqual(external_embedding.payload["embedding_provider"]["model_id"], "text-embedding-3-large")
        self.assertEqual(external_embedding.payload["embedding_provider"]["secret_status"], "stored")
        local_embedding = self.app.dispatch(
            "POST",
            "/v1/providers/embeddings",
            body=self._body({"source": "elephant-embed"}),
        )
        self.assertEqual(local_embedding.status_code, 200)
        self.assertEqual(local_embedding.payload["embedding_provider"]["source"], "local-default")
        self.assertIn(
            local_embedding.payload["embedding_provider"]["embedding_bootstrap_status"],
            EMBEDDING_BOOTSTRAP_STATUSES,
        )

        doctor = self.app.dispatch("GET", "/v1/providers/doctor")
        self.assertEqual(doctor.status_code, 200)
        self.assertEqual(doctor.payload["status"], "ready")
        self.assertEqual(doctor.payload["active_provider"]["provider_id"], "openai-compatible")
        self.assertIn("runtime", [check["check"] for check in doctor.payload["checks"]])
        self.assertIn("embedding_bootstrap", [check["check"] for check in doctor.payload["checks"]])

        test = self.app.dispatch(
            "POST",
            "/v1/providers/test",
            body=self._body({"prompt": "Summarize the provider setup."}),
        )
        self.assertEqual(test.status_code, 200)
        self.assertEqual(test.payload["result"]["summary"], "live-chat:Summarize the provider setup.")

        created = self.app.dispatch(
            "POST",
            "/v1/episodes",
            body=self._body(
                {
                    "profile_id": "profile-defaulted",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "episode_id": "session-defaulted",
                }
            ),
        )
        self.assertEqual(created.status_code, 201)

        turn = self.app.dispatch(
            "POST",
            "/v1/episodes/session-defaulted/loops",
            body=self._body({"prompt": "What should we do next?"}),
        )
        self.assertEqual(turn.status_code, 200)
        execution = (
            turn.payload["outcome"].execution
            if hasattr(turn.payload["outcome"], "execution")
            else turn.payload["outcome"]["execution"]
        )
        execution_summary = execution.summary if hasattr(execution, "summary") else execution["summary"]
        self.assertTrue(
            execution_summary.startswith(
                "live-chat:What should we do next?"
            )
        )
        inspection = turn.payload["inspection"]
        provider_profile = (
            inspection.provider_profile
            if hasattr(inspection, "provider_profile")
            else inspection["provider_profile"]
        )
        provider_id = (
            provider_profile.provider_id
            if hasattr(provider_profile, "provider_id")
            else provider_profile["provider_id"]
        )
        self.assertEqual(provider_id, "openai-compatible")
        dashboard = self.app.dispatch("GET", "/v1/internal/dashboard/usage")
        self.assertEqual(dashboard.status_code, 200)
        usage = dashboard.payload["dashboard"]["operations"]["usage"]
        self.assertGreaterEqual(usage["summary"]["runtimeStepUsageEvents"], 1)
        self.assertTrue(usage["tokenEvents"])

    def test_api_runtime_restores_active_provider_from_profile_manifest(self) -> None:
        root = Path(self.tempdir.name) / "restored-runtime"
        state_dir = root / "state"
        profile_dir = root / "profile"
        state_dir.mkdir(parents=True)
        profile_dir.mkdir(parents=True)
        config_path = global_config_path_for_state_dir(state_dir)
        config_path.write_text(
            json.dumps(
                {
                    "runtime": {
                        "state_dir": str(state_dir),
                        "default_profile_id": "default",
                    },
                    "models": {
                        "default_provider_source": "config",
                        "provider": self._provider_profile(
                            profile_id="provider-openrouter",
                            base_url=self.stub.openai_base_url,
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )
        app = create_app(database_path=state_dir / "elephant.sqlite3", install_root=root)

        doctor = app.dispatch("GET", "/v1/providers/doctor")

        self.assertEqual(doctor.status_code, 200)
        self.assertEqual(doctor.payload["status"], "ready")
        self.assertEqual(doctor.payload["active_provider"]["source"], "configured")
        self.assertEqual(doctor.payload["active_provider"]["provider_id"], "openai-compatible")
        self.assertEqual(doctor.payload["active_provider"]["model_id"], "openai/gpt-4o-mini")
        self.assertNotIn("strong_model", doctor.payload["active_provider"])
        self.assertNotIn("weak_model", doctor.payload["active_provider"])

    def test_default_provider_profile_stays_non_blocking(self) -> None:
        provider_profile = self._provider_profile(
            profile_id="provider-openrouter",
            base_url=self.stub.openai_base_url,
        )

        defaulted = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body({"provider_profile": provider_profile}),
        )
        self.assertEqual(defaulted.status_code, 200)
        self.assertEqual(defaulted.payload["active_provider"]["model_id"], "openai/gpt-4o-mini")
        self.assertNotIn("state_focus_mode", defaulted.payload["active_provider"])
        self.assertIn(
            defaulted.payload["active_provider"]["embedding_bootstrap_status"],
            EMBEDDING_BOOTSTRAP_STATUSES,
        )

        doctor = self.app.dispatch("GET", "/v1/providers/doctor")
        self.assertEqual(doctor.status_code, 200)
        bootstrap_check = next(
            check for check in doctor.payload["checks"] if check["check"] == "embedding_bootstrap"
        )
        self.assertIn(bootstrap_check["status"], EMBEDDING_BOOTSTRAP_STATUSES)
        self.assertEqual(doctor.payload["status"], "ready")

    def test_default_provider_model_update_reuses_active_profile_endpoint(self) -> None:
        provider_profile = self._provider_profile(
            profile_id="provider-openrouter",
            base_url=self.stub.openai_base_url,
            extra_headers={"x-tenant": "elephant"},
        )

        defaulted = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body({"provider_profile": provider_profile}),
        )
        self.assertEqual(defaulted.status_code, 200)

        updated = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body(
                {
                    "provider_profile": {
                        "profile_id": "provider-openrouter",
                        "provider_id": "openai-compatible",
                        "default_model": "openai/gpt-4.1-mini",
                        "metadata": {"context_window_mode": "auto"},
                    }
                }
            ),
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.payload["provider_profile"]["base_url"], self.stub.openai_base_url)
        self.assertEqual(updated.payload["provider_profile"]["default_model"], "openai/gpt-4.1-mini")
        self.assertEqual(updated.payload["provider_profile"]["extra_headers"], {"x-tenant": "elephant"})
        self.assertEqual(updated.payload["active_provider"]["base_url"], self.stub.openai_base_url)
        self.assertEqual(updated.payload["active_provider"]["model_id"], "openai/gpt-4.1-mini")

    def test_default_provider_bad_request_hides_legacy_profile_field_names(self) -> None:
        response = self.app.dispatch(
            "POST",
            "/v1/providers/default",
            body=self._body({"provider_profile": "invalid"}),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.payload["detail"],
            "provider_profile must be an object describing the default provider configuration",
        )



if __name__ == "__main__":
    unittest.main()
