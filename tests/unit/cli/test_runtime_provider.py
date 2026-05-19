from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock

from apps.cli.runtime import CliRuntime
from packages.auth import AuthProfile, SecretReference


class CliRuntimeProviderMetadataTest(unittest.TestCase):
    def _runtime(self, *, model_provider) -> CliRuntime:
        repository = mock.Mock()
        repository.load_auth_profile.return_value = None
        return CliRuntime(
            paths=mock.Mock(),
            repository=repository,
            profile_loader=mock.Mock(),
            snapshot_path=Path("/tmp/elephant-cli-runtime-provider-snapshot.json"),
            recall_runtime=mock.Mock(),
            cron_runtime=mock.Mock(),
            model_provider=model_provider,
            tool_runtime=mock.Mock(),
            skill_runtime=mock.Mock(),
            skill_hub=mock.Mock(),
            skill_search_hub=mock.Mock(),
            security_policy=mock.Mock(),
        )

    def test_discover_provider_models_uses_discovered_credentials_when_profile_is_inactive(
        self,
    ) -> None:
        model_provider = mock.Mock()
        model_provider.active_profile.return_value = None
        model_provider.resolve_discovered_credentials.return_value = {"api_key": "ghu-discovered"}
        model_provider.discover_models.return_value = ("copilot-models",)

        runtime = self._runtime(model_provider=model_provider)

        models = runtime.discover_provider_models(
            provider_id="copilot",
            base_url="https://api.githubcopilot.com",
        )

        self.assertEqual(models, ("copilot-models",))
        model_provider.discover_models.assert_called_once_with(
            provider_id="copilot",
            base_url="https://api.githubcopilot.com",
            api_key="ghu-discovered",
        )

    def test_provider_doctor_rejects_placeholder_model_before_runtime_probe(
        self,
    ) -> None:
        model_provider = mock.Mock()
        model_provider.describe.return_value = {
            "provider_id": "openai-compatible",
            "source": "configured",
            "secret_status": "stored",
            "secret_source": "encrypted-local-store",
            "model_id": "model-id",
            "base_url": "https://api.example.test/v1",
        }
        model_provider.runtime_resolver.build_setup_guide.return_value = mock.Mock(
            as_mapping=mock.Mock(return_value={})
        )
        runtime = self._runtime(model_provider=model_provider)

        with (
            mock.patch.object(CliRuntime, "discover_provider_models", autospec=True, return_value=()),
            mock.patch.object(
                CliRuntime,
                "provider_test",
                autospec=True,
            ) as provider_test,
        ):
            report = runtime.provider_doctor()

        provider_test.assert_not_called()
        runtime_check = next(check for check in report["checks"] if check["check"] == "runtime")
        self.assertEqual(runtime_check["status"], "not-ready")
        self.assertIn("placeholder", runtime_check["summary"])

    def test_provider_doctor_surfaces_embedding_bootstrap_state(self) -> None:
        model_provider = mock.Mock()
        model_provider.describe.return_value = {
            "provider_id": "openai-compatible",
            "source": "configured",
            "secret_status": "stored",
            "secret_source": "encrypted-local-store",
            "model_id": "openai/gpt-4o-mini",
            "base_url": "https://api.example.test/v1",
            "embedding_bootstrap_status": "pending",
            "embedding_bootstrap_summary": "local semantic-index bootstrap is preparing minimal sentence-transformers dependencies in the background.",
        }
        model_provider.runtime_resolver.build_setup_guide.return_value = mock.Mock(
            as_mapping=mock.Mock(return_value={})
        )
        runtime = self._runtime(model_provider=model_provider)

        with (
            mock.patch.object(CliRuntime, "discover_provider_models", autospec=True, return_value=()),
            mock.patch.object(
                CliRuntime,
                "provider_test",
                autospec=True,
                return_value=mock.Mock(summary="Doctor check"),
            ),
        ):
            report = runtime.provider_doctor()

        bootstrap_check = next(check for check in report["checks"] if check["check"] == "embedding_bootstrap")
        self.assertEqual(bootstrap_check["status"], "pending")
        self.assertIn("background", bootstrap_check["summary"])

    def test_provider_doctor_shallow_skips_live_catalog_and_probe(self) -> None:
        model_provider = mock.Mock()
        model_provider.describe.return_value = {
            "provider_id": "openai-compatible",
            "source": "configured",
            "secret_status": "stored",
            "secret_source": "encrypted-local-store",
            "model_id": "openai/gpt-4o-mini",
            "base_url": "https://api.example.test/v1",
            "embedding_bootstrap_status": "ready",
            "embedding_bootstrap_summary": "local bootstrap is ready",
        }
        model_provider.runtime_resolver.build_setup_guide.return_value = mock.Mock(
            as_mapping=mock.Mock(return_value={})
        )
        runtime = self._runtime(model_provider=model_provider)

        with (
            mock.patch.object(CliRuntime, "discover_provider_models", autospec=True) as discover,
            mock.patch.object(
                CliRuntime,
                "provider_test",
                autospec=True,
            ) as provider_test,
        ):
            report = runtime.provider_doctor(deep=False)

        discover.assert_not_called()
        provider_test.assert_not_called()
        self.assertEqual(report["status"], "ready")
        self.assertNotIn("model_catalog", {check["check"] for check in report["checks"]})
        self.assertNotIn("runtime", {check["check"] for check in report["checks"]})

    def test_embedding_provider_summary_defaults_to_local_provider(self) -> None:
        model_provider = mock.Mock()
        model_provider.describe.return_value = {
            "embedding_bootstrap_status": "ready",
            "embedding_bootstrap_summary": "local bootstrap is ready",
        }
        runtime = self._runtime(model_provider=model_provider)

        summary = dict(runtime.embedding_provider_summary())

        self.assertEqual(summary["source"], "local-default")
        self.assertEqual(summary["secret_status"], "not-required")
        self.assertEqual(summary["embedding_bootstrap_status"], "ready")

    def test_set_openai_compatible_embedding_provider_persists_override(self) -> None:
        model_provider = mock.Mock()
        model_provider.describe.return_value = {}
        model_provider.secret_cipher.decrypt.return_value = "sk-existing"
        runtime = self._runtime(model_provider=model_provider)
        runtime.repository.has_auth_secret_value.return_value = True

        summary = dict(
            runtime.set_openai_compatible_embedding_provider(
                base_url="https://api.example.test/v1",
                model_id="text-embedding-3-large",
                dimensions=1536,
                api_key="sk-embed-test",
                secret_env_var="OPENAI_API_KEY",
            )
        )

        runtime.repository.upsert_auth_profile.assert_called_once()
        model_provider.store_secret_value.assert_called_once()
        profile = runtime.repository.upsert_auth_profile.call_args.args[0]
        self.assertEqual(profile.profile_id, "provider-embedding-openai-compatible")
        self.assertEqual(profile.metadata["embedding_active"], "true")
        self.assertEqual(profile.metadata["dimensions"], "1536")
        self.assertEqual(summary["source"], "configured")
        self.assertEqual(summary["provider_id"], "openai-compatible-embed")
        self.assertEqual(summary["dimensions"], 1536)
        self.assertEqual(summary["secret_status"], "stored")

    def test_set_local_embedding_provider_marks_override_inactive(self) -> None:
        model_provider = mock.Mock()
        model_provider.describe.return_value = {
            "embedding_bootstrap_status": "ready",
            "embedding_bootstrap_summary": "local bootstrap is ready",
        }
        model_provider.ensure_embedding_bootstrap_state.return_value = mock.Mock(status="pending")
        runtime = self._runtime(model_provider=model_provider)
        active_profile = AuthProfile(
            profile_id="provider-embedding-openai-compatible",
            provider_id="openai-compatible-embed",
            transport_id="openai-compatible",
            base_url="https://api.example.test/v1",
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
                        "env_var": "OPENAI_API_KEY",
                    },
                ),
            ),
            metadata={"embedding_active": "true", "dimensions": "1536"},
        )
        inactive_profile = AuthProfile(
            profile_id=active_profile.profile_id,
            provider_id=active_profile.provider_id,
            transport_id=active_profile.transport_id,
            base_url=active_profile.base_url,
            default_model=active_profile.default_model,
            auth_method=active_profile.auth_method,
            provider_kind=active_profile.provider_kind,
            secret_references=active_profile.secret_references,
            metadata={"embedding_active": "false", "dimensions": "1536"},
        )
        runtime.repository.load_auth_profile.side_effect = [
            active_profile,
            inactive_profile,
        ]

        summary = dict(runtime.set_local_embedding_provider())

        runtime.repository.upsert_auth_profile.assert_called_once()
        model_provider.ensure_embedding_bootstrap_state.assert_called_once_with(source="huggingface")
        stored = runtime.repository.upsert_auth_profile.call_args.args[0]
        self.assertEqual(stored.metadata["embedding_active"], "false")
        self.assertEqual(summary["source"], "local-default")
        self.assertEqual(summary["embedding_bootstrap_status"], "ready")
        self.assertEqual(summary["embedding_bootstrap_summary"], "local bootstrap is ready")


if __name__ == "__main__":
    unittest.main()
